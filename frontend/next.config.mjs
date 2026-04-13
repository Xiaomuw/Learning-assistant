/** @type {import('next').NextConfig} */
const apiProxyBase = (
  process.env.INTERNAL_API_BASE ??
  process.env.NEXT_PUBLIC_API_BASE ??
  "http://127.0.0.1:8000/api"
).replace(/\/$/, "");

const nextConfig = {
  // 代理后端 API，避免跨域
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiProxyBase}/:path*`,
      },
    ];
  },
};

export default nextConfig;
