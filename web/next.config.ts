import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  // Allow reading markdown reports from repo root ../reports
  outputFileTracingRoot: path.join(__dirname, ".."),
  outputFileTracingIncludes: {
    "/": ["../reports/**/*"],
  },
};

export default nextConfig;
