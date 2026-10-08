/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  reactStrictMode: true,
  poweredByHeader: false,
  experimental: {
    // File uploads go through a Server Action; the API caps files at 50 MB.
    serverActions: { bodySizeLimit: '52mb' },
  },
};

export default nextConfig;
