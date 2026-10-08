import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'TaxResearch POC - Home',
};

async function getApiHealth() {
  const apiUrl = process.env.API_URL || 'http://localhost:8000';
  const timeout = 5000;

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);

    const response = await fetch(`${apiUrl}/health`, {
      signal: controller.signal,
      cache: 'no-store',
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      return { status: 'error', message: `HTTP ${response.status}` };
    }

    const data = await response.json();
    return { status: 'ok', data };
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      return { status: 'error', message: 'API request timed out' };
    }
    return {
      status: 'error',
      message: error instanceof Error ? error.message : 'Unknown error',
    };
  }
}

export default async function Home() {
  const health = await getApiHealth();

  return (
    <main style={{ padding: '2rem', fontFamily: 'sans-serif' }}>
      <h1>TaxResearch POC</h1>
      <p>A research platform for Indian GST law.</p>

      <section style={{ marginTop: '2rem' }}>
        <h2>API Health</h2>
        {health.status === 'ok' ? (
          <div style={{ padding: '1rem', backgroundColor: '#e8f5e9', borderRadius: '4px' }}>
            <p style={{ color: '#2e7d32', fontWeight: 'bold' }}>✓ API is running</p>
            <pre style={{ overflow: 'auto', fontSize: '0.9rem' }}>
              {JSON.stringify(health.data, null, 2)}
            </pre>
          </div>
        ) : (
          <div style={{ padding: '1rem', backgroundColor: '#ffebee', borderRadius: '4px' }}>
            <p style={{ color: '#c62828', fontWeight: 'bold' }}>✗ API unreachable</p>
            <p>{health.message}</p>
          </div>
        )}
      </section>

      <section style={{ marginTop: '2rem' }}>
        <h2>Quick Links</h2>
        <ul>
          <li>
            <a href="http://localhost:8000/docs">API Documentation</a>
          </li>
          <li>
            <a href="http://localhost:9001">MinIO Console</a> (S3 storage)
          </li>
        </ul>
      </section>

      <footer style={{ marginTop: '4rem', color: '#666', fontSize: '0.9rem' }}>
        <p>Status: v0.2 Draft · See FSD.md and TSD.md for specifications</p>
      </footer>
    </main>
  );
}
