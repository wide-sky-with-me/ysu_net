<script lang="ts">
  let { name, size = 18 }: { name: string; size?: number } = $props();
  const paths: Record<string, string> = {
    network: 'M4 8h6V4H4v4Zm10 0h6V4h-6v4ZM9 20h6v-4H9v4ZM7 8v4h10V8M12 12v4',
    connect: 'M8 3v5m8-5v5M6 8h12v3a6 6 0 0 1-6 6v4M6 8v3a6 6 0 0 0 6 6',
    account: 'M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0ZM4 21v-3a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v3',
    settings: 'M4 8h3M11 8h9M4 16h9M17 16h3M11 8a2 2 0 1 1-4 0 2 2 0 0 1 4 0M17 16a2 2 0 1 1-4 0 2 2 0 0 1 4 0',
    logs: 'M7 3h7l4 4v14H7V3Zm7 0v4h4M10 12h5M10 16h5',
    refresh: 'M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8M21 3v5h-5M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16M8 16H3v5',
    check: 'm5 12 4 4L19 6',
    close: 'm6 6 12 12M6 18 18 6',
    shield: 'm12 3 8 3v6c0 4-4 7-8 9-4-2-8-5-8-9V6l8-3Zm-4 9 3 3 5-6',
    browser: 'M3 5h18v14H3V5Zm0 4h18M6 7.5h.8',
    copy: 'M9 8h11v13H9V8ZM5 16H3V3h11v2',
    eye: 'M2 12s3-6 10-6 10 6 10 6-3 6-10 6S2 12 2 12Zm13 0a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z',
    doctor: 'M3 12h3.5l2.2-5.8 3.4 11 2.2-5.2H21',
    exit: 'M9 4H4v16h5m0-8h12m-4-4 4 4-4 4',
    power: 'M12 3v8M6.3 6.3a8 8 0 1 0 11.4 0',
    search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14M16 16l5 5',
    info: 'M13.2 7.9a1.2 1.2 0 1 1-2.4 0 1.2 1.2 0 0 1 2.4 0M12 11.6v4.8M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z',
    alert: 'M15 9l-6 6M9 9l6 6M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z',
  };
</script>

<svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <path d={paths[name] || paths.info} />
</svg>
