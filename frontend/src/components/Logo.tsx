// Navi's logo (a licence with a compass), drawn from public/logo.svg at whatever size is asked for.

export function Logo({ size = 32 }: { size?: number }) {
  return <img src="/logo.svg" width={size} height={size} alt="" className="shrink-0" />;
}
