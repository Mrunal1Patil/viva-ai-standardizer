import { useState } from 'react';

export default function Home() {
  const [idealFile, setIdealFile] = useState(null);
  const [rawFile, setRawFile] = useState(null);
  const [instFile, setInstFile] = useState(null);
  const [msg, setMsg] = useState('');
  const [downlinks, setDownlinks] = useState(null); // {idealUrl, logUrl, summaryUrl}
  const [loading, setLoading] = useState(false);

  const onSubmit = async (e) => {
    e.preventDefault();
    setMsg('Processing…');
    setLoading(true);
    setDownlinks(null);

    const fd = new FormData();
    fd.append('ideal', idealFile);
    fd.append('raw', rawFile);
    fd.append('instructions', instFile);

    try {
      const res = await fetch('http://localhost:8080/api/process', {
        method: 'POST',
        body: fd
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      setMsg('Done! Downloads ready below.');
      setDownlinks({
        idealUrl: `http://localhost:8080${data.idealUrl}`,
        logUrl: `http://localhost:8080${data.logUrl}`,
        summaryUrl: `http://localhost:8080${data.summaryUrl}`
      });
    } catch (err) {
      console.error(err);
      setMsg('Failed to process. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const canSubmit = idealFile && rawFile && instFile;

  return (
    <div className="centered">
      <div className="card" style={{ maxWidth: 640 }}>
        <h1 className="title">One-Click Ideal Sheet Generator</h1>

        <form onSubmit={onSubmit}>
          <label className="label">Ideal template (XLSX)</label>
          <input
            type="file"
            className="input"
            accept=".xls,.xlsx"
            onChange={e => setIdealFile(e.target.files[0] || null)}
          />

          <div style={{ height: 12 }} />
          <label className="label">Raw spreadsheet (CSV/XLSX)</label>
          <input
            type="file"
            className="input"
            accept=".csv,.xls,.xlsx"
            onChange={e => setRawFile(e.target.files[0] || null)}
          />

          <div style={{ height: 12 }} />
          <label className="label">Instructions (PDF/XLSX/DOC)</label>
          <input
            type="file"
            className="input"
            onChange={e => setInstFile(e.target.files[0] || null)}
          />

          <div style={{ height: 16 }} />
          <button type="submit" className="btn" disabled={!canSubmit || loading}>
            {loading ? 'Working…' : (canSubmit ? 'Generate Ideal Spreadsheet' : 'Select all three files')}
          </button>

          {msg && <p className="msg">{msg}</p>}
        </form>

        {downlinks && (
          <div style={{ marginTop: 16 }}>
            <p className="label" style={{ marginBottom: 8 }}>Downloads:</p>
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              <li><a className="link" href={downlinks.idealUrl}>Ideal spreadsheet</a></li>
              <li><a className="link" href={downlinks.logUrl}>YAML transform log</a></li>
              <li><a className="link" href={downlinks.summaryUrl}>Summary report</a></li>
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}