/** @type {import('next').NextConfig} */
const nextConfig = {
  typedRoutes: true,
  // Allow importing from src/ via @/src/... path alias
  webpack(config) {
    return config;
  },
};

export default nextConfig;
