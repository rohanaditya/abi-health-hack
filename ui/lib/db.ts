import { Pool } from "pg";

declare global {
  // eslint-disable-next-line no-var
  var _pgPool: Pool | undefined;
}

function getPool(): Pool {
  if (!global._pgPool) {
    const url = process.env.DATABASE_URL;
    if (!url) throw new Error("DATABASE_URL is not set");

    // Parse the URL manually to handle encoded chars in password
    const parsed = new URL(url);
    global._pgPool = new Pool({
      host: parsed.hostname,
      port: Number(parsed.port) || 5432,
      user: parsed.username,
      password: decodeURIComponent(parsed.password),
      database: parsed.pathname.replace(/^\//, ""),
      ssl: { rejectUnauthorized: false },
      max: 5,
    });
  }
  return global._pgPool;
}

export { getPool };
