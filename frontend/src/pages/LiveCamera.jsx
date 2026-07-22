import { useEffect, useRef, useState } from 'react';
import { api, getToken } from '../api/client';
import Badge from '../components/Badge';
import Spinner from '../components/Spinner';
import Icon from '../components/Icons';
import { fmtScore } from '../utils/format';

/** Normalizes a face box from any common shape to {x, y, w, h}. */
function normalizeBox(box) {
  if (!box) return null;
  if (Array.isArray(box)) {
    const [a, b, c, d] = box.map(Number);
    return { x: a, y: b, w: c, h: d };
  }
  if (typeof box === 'object') {
    if ('x' in box && 'y' in box) {
      return {
        x: Number(box.x),
        y: Number(box.y),
        w: Number(box.w ?? box.width ?? 0),
        h: Number(box.h ?? box.height ?? 0),
      };
    }
    if ('left' in box && 'top' in box) {
      const x = Number(box.left);
      const y = Number(box.top);
      const w = 'width' in box ? Number(box.width) : Number(box.right) - x;
      const h = 'height' in box ? Number(box.height) : Number(box.bottom) - y;
      return { x, y, w, h };
    }
  }
  return null;
}

export default function LiveCamera() {
  const [status, setStatus] = useState(null);
  const [statusError, setStatusError] = useState('');
  const [streamKey, setStreamKey] = useState(0);
  const [streamFailed, setStreamFailed] = useState(false);
  // AI overlay: server-side recognition drawn onto the MJPEG stream
  const [aiOverlay, setAiOverlay] = useState(false);

  // Snapshot test state
  const [file, setFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [imgDims, setImgDims] = useState(null);
  const [result, setResult] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState('');
  const fileRef = useRef(null);

  const loadStatus = () => {
    setStatusError('');
    api
      .get('/api/camera/status')
      .then(setStatus)
      .catch((e) => {
        setStatus({ available: false });
        setStatusError(e.message);
      });
  };

  useEffect(loadStatus, []);

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  const pickFile = (f) => {
    if (!f) return;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setFile(f);
    setPreviewUrl(URL.createObjectURL(f));
    setImgDims(null);
    setResult(null);
    setAnalyzeError('');
  };

  const analyze = async () => {
    if (!file) return;
    setAnalyzing(true);
    setAnalyzeError('');
    setResult(null);
    try {
      const data = await api.upload('/api/recognition/frame', file);
      setResult(data);
    } catch (e) {
      setAnalyzeError(e.message);
    } finally {
      setAnalyzing(false);
    }
  };

  const faces = result?.faces || [];
  const streamUrl = `/api/camera/stream?token=${encodeURIComponent(getToken() || '')}${
    aiOverlay ? '&analyze=1' : ''
  }&k=${streamKey}`;

  return (
    <div className="page">
      <div className="card pad">
        <div className="card-title-row">
          <h2>Live Feed</h2>
          <div className="row-gap">
            {status && (
              <>
                <Badge value={status.available ? 'online' : 'offline'}>
                  {status.available ? 'Camera Online' : 'Camera Offline'}
                </Badge>
                {status.source !== undefined && (
                  <span className="muted-text">source: {String(status.source)}</span>
                )}
              </>
            )}
            <button
              className={aiOverlay ? 'btn btn-primary' : 'btn btn-secondary'}
              title="Run live face recognition on the stream (boxes + names drawn server-side)"
              onClick={() => {
                setAiOverlay((v) => !v);
                setStreamFailed(false);
                setStreamKey((k) => k + 1);
              }}
            >
              <Icon name="eye" size={15} /> AI Overlay {aiOverlay ? 'On' : 'Off'}
            </button>
            <button
              className="btn btn-ghost"
              onClick={() => {
                loadStatus();
                setStreamFailed(false);
                setStreamKey((k) => k + 1);
              }}
            >
              <Icon name="refresh" size={15} /> Reconnect
            </button>
          </div>
        </div>
        {statusError && <div className="error-text">{statusError}</div>}
        <div className="stream-frame">
          {status === null ? (
            <Spinner />
          ) : status.available && !streamFailed ? (
            <img
              key={streamKey}
              className="stream-img"
              src={streamUrl}
              alt="Live camera stream"
              onError={() => setStreamFailed(true)}
            />
          ) : (
            <div className="stream-offline">
              <Icon name="camera" size={40} />
              <p>{streamFailed ? 'Stream unavailable — try reconnecting.' : 'Camera is offline.'}</p>
            </div>
          )}
        </div>
      </div>

      <div className="card pad">
        <div className="card-title-row">
          <h2>Snapshot Test</h2>
          <span className="muted-text">Upload an image to run recognition on a single frame</span>
        </div>
        <div className="row-gap wrap">
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            hidden
            onChange={(e) => pickFile(e.target.files?.[0])}
          />
          <button className="btn btn-secondary" onClick={() => fileRef.current?.click()}>
            <Icon name="upload" size={15} /> Choose Image
          </button>
          {file && <span className="muted-text">{file.name}</span>}
          <button className="btn btn-primary" onClick={analyze} disabled={!file || analyzing}>
            {analyzing ? 'Analyzing…' : 'Analyze Frame'}
          </button>
        </div>
        {analyzeError && <div className="error-text spaced-top">{analyzeError}</div>}

        {previewUrl && (
          <div className="snapshot-layout">
            <div className="snapshot-preview">
              <img
                src={previewUrl}
                alt="Snapshot preview"
                onLoad={(e) =>
                  setImgDims({
                    w: e.target.naturalWidth,
                    h: e.target.naturalHeight,
                  })
                }
              />
              {imgDims && faces.length > 0 && (
                <svg
                  className="snapshot-overlay"
                  viewBox={`0 0 ${imgDims.w} ${imgDims.h}`}
                  preserveAspectRatio="none"
                >
                  {faces.map((f, i) => {
                    const b = normalizeBox(f.box);
                    if (!b) return null;
                    const stroke = f.match ? 'var(--ok)' : 'var(--danger)';
                    return (
                      <g key={i}>
                        <rect
                          x={b.x}
                          y={b.y}
                          width={b.w}
                          height={b.h}
                          fill="none"
                          stroke={stroke}
                          strokeWidth={Math.max(2, imgDims.w / 300)}
                        />
                        <text
                          x={b.x}
                          y={Math.max(b.y - 6, 14)}
                          fill={stroke}
                          fontSize={Math.max(12, imgDims.w / 40)}
                          fontWeight="600"
                        >
                          {f.match ? f.match.name : 'Unknown'}
                        </text>
                      </g>
                    );
                  })}
                </svg>
              )}
            </div>

            {result && (
              <div className="snapshot-results">
                <h3>
                  {faces.length} face{faces.length === 1 ? '' : 's'} detected
                </h3>
                {faces.length === 0 && (
                  <p className="muted-text">No faces found in this frame.</p>
                )}
                {faces.map((f, i) => (
                  <div key={i} className="face-result">
                    <div className="face-result-head">
                      <strong>{f.match ? f.match.name : 'Unknown person'}</strong>
                      <Badge value={f.match ? 'online' : 'offline'}>
                        {f.match ? 'Match' : 'No match'}
                      </Badge>
                    </div>
                    <div className="face-result-meta">
                      {f.match && (
                        <span>
                          {f.match.department_name || '—'} · {f.match.employee_id || ''}
                        </span>
                      )}
                      <span>Match score: {fmtScore(f.score)}</span>
                      <span>Detection confidence: {fmtScore(f.confidence)}</span>
                      {f.liveness !== undefined && f.liveness !== null && (
                        <span>
                          Liveness:{' '}
                          {typeof f.liveness === 'object'
                            ? f.liveness.passed === null
                              ? `checking (${f.liveness.method})`
                              : `${f.liveness.passed ? 'Live' : 'Spoof'} (${f.liveness.method})`
                            : typeof f.liveness === 'boolean'
                              ? f.liveness
                                ? 'Live'
                                : 'Spoof'
                              : fmtScore(f.liveness)}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
