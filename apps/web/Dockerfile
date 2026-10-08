# Web app Dockerfile - Next.js multi-stage build
FROM docker.io/library/node:22-slim as builder

WORKDIR /app

# Copy package files
COPY apps/web/package*.json ./

# Install dependencies
RUN npm ci

# Copy source code
COPY apps/web/ .

# Build Next.js app
RUN npm run build

# Runtime stage
FROM docker.io/library/node:22-slim

WORKDIR /app

# Create non-root user
RUN useradd -m -u 1000 appuser

# Copy built application from builder
COPY --from=builder /app/package*.json ./
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

# Install production dependencies only
RUN npm ci --production

# Change ownership
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
    CMD node -e "require('http').get('http://localhost:3000', (r) => {if (r.statusCode !== 200) throw new Error(r.statusCode)})" || exit 1

# Default environment
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Expose port
EXPOSE 3000

# Run the application
CMD ["node", "server.js"]
