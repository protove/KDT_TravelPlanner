import { connection } from "next/server";

type PingResponse = {
  application: string;
  profile: string;
  status: string;
};

type BackendStatus =
  | { connected: true; data: PingResponse }
  | { connected: false; message: string };

async function getBackendStatus(): Promise<BackendStatus> {
  await connection();

  const apiBaseUrl = process.env.INTERNAL_API_BASE_URL ?? "http://localhost:8080";

  try {
    const response = await fetch(`${apiBaseUrl}/api/ping`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });

    if (!response.ok) {
      return {
        connected: false,
        message: `Backend returned HTTP ${response.status}`,
      };
    }

    return {
      connected: true,
      data: (await response.json()) as PingResponse,
    };
  } catch (error) {
    return {
      connected: false,
      message: error instanceof Error ? error.message : "Unknown connection error",
    };
  }
}

export default async function Home() {
  const backend = await getBackendStatus();
  const publicApiUrl =
    process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8080";

  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-16">
      <section className="w-full max-w-3xl rounded-3xl border border-zinc-800 bg-zinc-950/80 p-8 shadow-2xl shadow-cyan-950/20 sm:p-12">
        <div className="mb-10 flex items-start justify-between gap-6">
          <div>
            <p className="mb-3 font-mono text-xs uppercase tracking-[0.3em] text-cyan-400">
              Docker environment
            </p>
            <h1 className="text-3xl font-semibold tracking-tight text-zinc-50 sm:text-4xl">
              Travel Diary
            </h1>
            <p className="mt-3 max-w-xl text-sm leading-6 text-zinc-400 sm:text-base">
              Next.js, Spring Boot, PostgreSQL, Redis 연결 상태를 확인합니다.
            </p>
          </div>
          <span
            className={`mt-1 inline-flex shrink-0 items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium ${
              backend.connected
                ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-300"
                : "border-rose-400/30 bg-rose-400/10 text-rose-300"
            }`}
          >
            <span
              className={`h-2 w-2 rounded-full ${backend.connected ? "bg-emerald-400" : "bg-rose-400"}`}
            />
            {backend.connected ? "Connected" : "Unavailable"}
          </span>
        </div>

        <dl className="grid gap-3 sm:grid-cols-2">
          <StatusItem label="Frontend" value="Next.js 16.2" healthy />
          <StatusItem
            label="Backend"
            value={backend.connected ? backend.data.application : backend.message}
            healthy={backend.connected}
          />
          <StatusItem
            label="Spring profile"
            value={backend.connected ? backend.data.profile : "unknown"}
            healthy={backend.connected}
          />
          <StatusItem label="Public API" value={publicApiUrl} healthy />
        </dl>

        <p className="mt-8 border-t border-zinc-800 pt-6 font-mono text-xs leading-5 text-zinc-500">
          페이지를 새로고침하면 서버에서 최신 상태를 다시 조회합니다.
        </p>
      </section>
    </main>
  );
}

function StatusItem({
  label,
  value,
  healthy,
}: {
  label: string;
  value: string;
  healthy: boolean;
}) {
  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900/70 p-5">
      <dt className="mb-2 text-xs font-medium uppercase tracking-wider text-zinc-500">
        {label}
      </dt>
      <dd className="flex items-center gap-2 break-all font-mono text-sm text-zinc-200">
        <span
          aria-hidden="true"
          className={`h-1.5 w-1.5 shrink-0 rounded-full ${healthy ? "bg-cyan-400" : "bg-rose-400"}`}
        />
        {value}
      </dd>
    </div>
  );
}
