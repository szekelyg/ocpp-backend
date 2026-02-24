export default function NotFound() {
    return (
      <div style={{ maxWidth: 720, margin: "40px auto", padding: 20, fontFamily: "system-ui" }}>
        <h1>404 – Nincs ilyen oldal</h1>
        <p>A kért oldal nem található.</p>
        <a href="/" style={{ display: "inline-block", marginTop: 16 }}>Vissza a főoldalra</a>
      </div>
    );
  }