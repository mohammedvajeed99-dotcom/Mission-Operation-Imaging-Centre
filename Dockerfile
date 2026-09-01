# ASC_074 Mission Operations Center — deployable image.
#
# Stage 1 builds the frontend, stage 2 runs the API and serves the built UI
# from the same process, so the whole application is one origin on one port.
#
# Product previews, thumbnails and metadata ARE shipped (~83 MB) so the Image
# Gallery is populated and every dashboard section works on the deployment.
# Only the full-resolution GeoTIFFs are excluded (~230 MB, see .dockerignore);
# they are regenerable on demand and the UI reports their absence explicitly.

# ---------------------------------------------------------------- frontend
FROM node:20-slim AS ui

WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci

COPY index.html ./
COPY logo.jpeg ./
COPY src ./src

# Empty API base => the UI calls its own origin, which is how it is served.
ENV VITE_API_BASE=""
RUN npm run build

# ----------------------------------------------------------------- runtime
FROM python:3.12-slim AS runtime

# No system GDAL/PROJ install here on purpose: the rasterio and pyproj
# wheels pip installs on Linux are manylinux wheels that bundle their own
# GDAL/PROJ shared libraries (confirmed locally -- rasterio ships its own
# gdal_data directory and linked GDAL build, independent of anything on the
# host). A prior version of this Dockerfile apt-get installed a
# version-pinned system libgdal package here, which broke the build the
# moment the python:3.12-slim base image's Debian release moved and that
# exact package name stopped existing -- removing it removes that fragility
# entirely rather than chasing the base image's package names.

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code and the mission data the analytics actually need.
COPY api.py api_image_center.py serve.py ./
COPY core ./core
COPY config ./config
COPY data ./data
COPY StateReport.txt ./

# The UI built in stage 1.
COPY --from=ui /build/dist ./dist

# Hosting platforms override this; it is only the local default.
ENV PORT=5001
EXPOSE 5001

# Access codes and the token signing secret MUST be supplied as environment
# variables in a hosted deployment. The filesystem here is ephemeral, so
# anything generated at runtime would be regenerated on the next restart,
# changing every code and invalidating every issued token.
#   ASC074_ACCESS_SECRET  - signing key (keep private)
#   ASC074_ACCESS_CODES   - JSON contents of config/access_codes.json
#   ASC074_WARM_CACHES=0  - skip startup warm-up on a memory-constrained plan

CMD ["python", "serve.py"]
