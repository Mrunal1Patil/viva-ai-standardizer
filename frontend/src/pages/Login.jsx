import { useState } from 'react';

export default function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [msg, setMsg] = useState('');

  const onSubmit = (e) => {
    e.preventDefault();
    setMsg(username && password ? '✅ Ready! Backend hook-up coming next.' : 'Please enter username and password.');
  };

  return (
    <div className="centered">
      <div className="card">
        <h1 className="title">Sign in</h1>
        <form onSubmit={onSubmit}>
          <label className="label">Username</label>
          <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="your.username" autoComplete="username" />
          <div style={{ height: 12 }} />
          <label className="label">Password</label>
          <input type="password" className="input" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" autoComplete="current-password" />
          <div style={{ height: 16 }} />
          <button type="submit" className="btn">Sign in</button>
          {msg && <p className="msg">{msg}</p>}
        </form>
      </div>
    </div>
  );
}