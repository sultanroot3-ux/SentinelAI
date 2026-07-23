import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import Badge from '../components/Badge';
import Spinner from '../components/Spinner';
import Icon from '../components/Icons';
import { fmtDateTime, fmtScore } from '../utils/format';

/** Small labelled value for report grids. */
function Field({ label, children }) {
  return (
    <div className="report-field">
      <span className="muted-text report-field-label">{label}</span>
      <span>{children ?? '—'}</span>
    </div>
  );
}

function EstimateValue({ data }) {
  if (data === null || data === undefined) return <span>—</span>;
  if (typeof data !== 'object') return <span>{String(data)}</span>;
  if (data.value === null || data.value === undefined) {
    return <span className="muted-text">{data.method || 'unavailable'}</span>;
  }
  return (
    <span>
      {String(data.value)}
      {data.estimate ? ` (${data.estimate})` : ''}
      {data.confidence ? (
        <span className="muted-text"> · {data.confidence} confidence</span>
      ) : null}
    </span>
  );
}

function AIAnalysis({ ai }) {
  if (!ai) return null;
  const pose = ai.head_pose_estimate;
  return (
    <div className="report-section">
      <h4>
        AI Analysis <Badge value="offline">Estimates only</Badge>
      </h4>
      <p className="muted-text">{ai.note}</p>
      <div className="report-grid">
        <Field label="Face quality">
          {ai.face_quality?.estimate} · {ai.face_quality?.face_size_px?.join('×')}px ·
          det {fmtScore(ai.face_quality?.detection_confidence)}
        </Field>
        <Field label="Blur">
          {ai.blur?.estimate} (score {ai.blur?.score})
        </Field>
        <Field label="Brightness">
          {ai.brightness?.estimate} ({ai.brightness?.value})
        </Field>
        <Field label="Estimated age">{ai.age_estimate ?? '—'}</Field>
        <Field label="Estimated gender">{ai.gender_estimate ?? '—'}</Field>
        <Field label="Emotion estimate">
          <EstimateValue data={ai.emotion_estimate} />
        </Field>
        <Field label="Head pose">
          {pose ? `pitch ${pose.pitch}° · yaw ${pose.yaw}° · roll ${pose.roll}°` : '—'}
        </Field>
        <Field label="Mask">
          <EstimateValue data={ai.mask_estimate} />
        </Field>
        <Field label="Glasses">
          <EstimateValue data={ai.glasses_estimate} />
        </Field>
      </div>
    </div>
  );
}

function FaceReport({ face }) {
  const isEmployee = face.person_type === 'employee';
  const loc = face.camera_location;
  return (
    <div className="card pad report-card">
      <div className="card-title-row">
        <h3>
          {isEmployee ? face.full_name : `Unknown person ${face.unknown_person_id || ''}`}
        </h3>
        <div className="row-gap">
          {face.watchlist_hits?.length > 0 && (
            <Badge value="offline">⚠ Watchlist: {face.watchlist_hits[0].watchlist}</Badge>
          )}
          <Badge value={isEmployee ? 'online' : 'offline'}>
            {isEmployee ? 'Registered employee' : 'Not in database'}
          </Badge>
        </div>
      </div>

      <div className="report-layout">
        {(face.snapshot_url || face.photo_url) && (
          <div className="report-photos">
            {face.snapshot_url && (
              <figure>
                <img src={face.snapshot_url} alt="Detection snapshot" />
                <figcaption className="muted-text">Snapshot</figcaption>
              </figure>
            )}
            {face.photo_url && (
              <figure>
                <img src={face.photo_url} alt="Registered profile" />
                <figcaption className="muted-text">Profile photo</figcaption>
              </figure>
            )}
          </div>
        )}

        <div className="report-body">
          {isEmployee ? (
            <div className="report-section">
              <h4>Employee Profile (database record)</h4>
              <div className="report-grid">
                <Field label="Employee ID">{face.employee_id}</Field>
                <Field label="Department">{face.department}</Field>
                <Field label="Job title">{face.job_title}</Field>
                <Field label="Office / building">{face.office_building}</Field>
                <Field label="Badge number">{face.badge_number}</Field>
                <Field label="Access level">{face.access_level}</Field>
                <Field label="Email">{face.email}</Field>
                <Field label="Phone">{face.phone}</Field>
                <Field label="Status">
                  <Badge value={face.status === 'active' ? 'online' : 'offline'}>
                    {face.status}
                  </Badge>
                </Field>
              </div>
            </div>
          ) : (
            <div className="report-section">
              <h4>Unknown Person</h4>
              <div className="report-grid">
                <Field label="Assigned ID">{face.unknown_person_id}</Field>
                <Field label="First recorded">{fmtDateTime(face.detection_time)}</Field>
              </div>
              {face.similar_prior_sightings?.length > 0 && (
                <>
                  <h4>Similar prior sightings (embedding match)</h4>
                  <ul className="report-list">
                    {face.similar_prior_sightings.map((s, i) => (
                      <li key={i}>
                        {s.unknown_person_id || '—'} · {fmtDateTime(s.timestamp)} ·{' '}
                        {s.camera} · similarity {fmtScore(s.similarity)}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}

          <div className="report-section">
            <h4>Detection</h4>
            <div className="report-grid">
              <Field label="Camera">{face.camera_name}</Field>
              <Field label="Location">
                {loc
                  ? [loc.name, loc.building, loc.floor && `Floor ${loc.floor}`, loc.room]
                      .filter(Boolean)
                      .join(' · ')
                  : '—'}
              </Field>
              <Field label="Detection time">{fmtDateTime(face.detection_time)}</Field>
              <Field label="Last seen">{fmtDateTime(face.last_seen)}</Field>
              <Field label="Recognition confidence">
                {fmtScore(face.recognition_confidence ?? face.best_match_score)}
              </Field>
              <Field label="Liveness">
                {face.liveness
                  ? `${face.liveness.passed ? 'passed' : 'not verified'} (${face.liveness.method})`
                  : '—'}
              </Field>
            </div>
          </div>

          {face.watchlist_hits?.length > 0 && (
            <div className="report-section">
              <h4>Watchlist Hits</h4>
              <ul className="report-list">
                {face.watchlist_hits.map((h, i) => (
                  <li key={i}>
                    <strong>{h.watchlist}</strong> ({h.level}) — {h.reason || 'no reason recorded'}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {isEmployee && face.recognition_history?.length > 0 && (
            <div className="report-section">
              <h4>Recognition History</h4>
              <ul className="report-list">
                {face.recognition_history.map((h, i) => (
                  <li key={i}>
                    {fmtDateTime(h.timestamp)} · {h.camera} · score {fmtScore(h.score)}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <AIAnalysis ai={face.ai_analysis} />
        </div>
      </div>
    </div>
  );
}

export default function Investigation() {
  const [searchParams] = useSearchParams();
  const [cameras, setCameras] = useState([]);
  const [camera, setCamera] = useState('webcam');
  const [file, setFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const fileRef = useRef(null);

  useEffect(() => {
    api
      .get('/api/cameras')
      .then((rows) => setCameras(rows || []))
      .catch(() => setCameras([]));
  }, []);

  // Deep links: /investigation?employee=ID or ?unknown=ID load a DB report
  useEffect(() => {
    const employeeId = searchParams.get('employee');
    const unknownId = searchParams.get('unknown');
    if (!employeeId && !unknownId) return;
    setLoading(true);
    setError('');
    api
      .get(
        employeeId
          ? `/api/investigation/employee/${employeeId}`
          : `/api/investigation/unknown/${unknownId}`
      )
      .then(setReport)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [searchParams]);

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
    setReport(null);
    setError('');
  };

  const analyze = async () => {
    if (!file) return;
    setLoading(true);
    setError('');
    setReport(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const data = await api.post(
        `/api/investigation/analyze?camera=${encodeURIComponent(camera)}`,
        fd
      );
      setReport(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page">
      <div className="card pad">
        <div className="card-title-row">
          <h2>Investigation</h2>
          <span className="muted-text">
            Identity data comes only from this system's database. AI attributes are estimates.
          </span>
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
          <select
            className="input"
            value={camera}
            onChange={(e) => setCamera(e.target.value)}
            title="Camera this frame came from"
          >
            {cameras.length === 0 && <option value="webcam">webcam</option>}
            {cameras.map((c) => (
              <option key={c.id} value={c.name}>
                {c.name}
                {c.location ? ` — ${c.location.name}` : ''}
              </option>
            ))}
          </select>
          <button className="btn btn-primary" onClick={analyze} disabled={!file || loading}>
            {loading ? 'Investigating…' : 'Run Investigation'}
          </button>
        </div>
        {error && <div className="error-text spaced-top">{error}</div>}
        {previewUrl && !report && !loading && (
          <div className="report-preview">
            <img src={previewUrl} alt="Frame to investigate" />
          </div>
        )}
        {loading && <Spinner />}
      </div>

      {report && (
        <>
          {report.faces.length === 0 && (
            <div className="card pad">
              <p className="muted-text">No faces detected in this frame.</p>
            </div>
          )}
          {report.faces.map((face, i) => (
            <FaceReport key={i} face={face} />
          ))}
          {report.scene && (
            <div className="card pad">
              <div className="card-title-row">
                <h3>Scene Analysis</h3>
                <Badge value="offline">Estimates only</Badge>
              </div>
              <div className="report-grid">
                <Field label="Description">{report.scene.description_estimate}</Field>
                <Field label="Resolution">{report.scene.resolution?.join('×')}</Field>
                <Field label="Brightness">
                  {report.scene.brightness?.estimate} ({report.scene.brightness?.value})
                </Field>
                <Field label="Object detection">
                  <EstimateValue data={report.scene.object_detection} />
                </Field>
                <Field label="OCR text">
                  <EstimateValue data={report.scene.ocr_text} />
                </Field>
              </div>
              <p className="muted-text spaced-top">{report.data_policy}</p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
