/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  typedRoutes: false,
  // Proxy /api/* to the FastAPI backend in dev so SSE works without CORS pain
  async rewrites() {
    const api = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
    return [
      { source: "/api/:path*", destination: `${api}/:path*` },
    ];
  },
};

export default nextConfig;
