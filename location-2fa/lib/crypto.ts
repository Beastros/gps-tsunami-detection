import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";

/** WGS-84 coordinates in decimal degrees. */
export interface Coordinates {
  latitude: number;
  longitude: number;
}

/** Inputs used to bind a login session to a location attestation. */
export interface LocationHmacPayload extends Coordinates {
  sessionId: string;
  timestamp: number;
}

export const DEFAULT_LOCATION_THRESHOLD_METERS = 2_000;
export const EARTH_RADIUS_METERS = 6_371_000;

/**
 * Rounds coordinates so HMAC generation is stable across minor GPS jitter.
 * Six decimal places is roughly 0.11 m precision at the equator.
 */
export function normalizeCoordinates(
  coordinates: Coordinates,
  precision = 6,
): Coordinates {
  const factor = 10 ** precision;
  return {
    latitude: Math.round(coordinates.latitude * factor) / factor,
    longitude: Math.round(coordinates.longitude * factor) / factor,
  };
}

/** Canonical string representation used for HMAC input. */
export function serializeLocationPayload(payload: LocationHmacPayload): string {
  const normalized = normalizeCoordinates(payload);
  return [
    normalized.latitude.toFixed(6),
    normalized.longitude.toFixed(6),
    payload.sessionId,
    payload.timestamp.toString(),
  ].join("|");
}

/** Create an HMAC-SHA256 digest for a location-bound login session. */
export function createLocationHmac(
  payload: LocationHmacPayload,
  secret: string,
): string {
  if (!secret) {
    throw new Error("HMAC secret is required");
  }

  return createHmac("sha256", secret)
    .update(serializeLocationPayload(payload))
    .digest("hex");
}

/** Constant-time comparison to avoid leaking HMAC prefix information. */
export function verifyLocationHmac(
  payload: LocationHmacPayload,
  secret: string,
  expectedHmac: string,
): boolean {
  if (!expectedHmac) {
    return false;
  }

  const actual = createLocationHmac(payload, secret);
  const actualBuffer = Buffer.from(actual, "hex");
  const expectedBuffer = Buffer.from(expectedHmac, "hex");

  if (actualBuffer.length !== expectedBuffer.length) {
    return false;
  }

  return timingSafeEqual(actualBuffer, expectedBuffer);
}

/**
 * Haversine distance between two coordinates.
 * Returns meters along the Earth's surface.
 */
export function haversineDistanceMeters(
  from: Coordinates,
  to: Coordinates,
): number {
  const toRadians = (degrees: number) => (degrees * Math.PI) / 180;
  const deltaLatitude = toRadians(to.latitude - from.latitude);
  const deltaLongitude = toRadians(to.longitude - from.longitude);
  const fromLatitude = toRadians(from.latitude);
  const toLatitude = toRadians(to.latitude);

  const haversine =
    Math.sin(deltaLatitude / 2) ** 2 +
    Math.cos(fromLatitude) *
      Math.cos(toLatitude) *
      Math.sin(deltaLongitude / 2) ** 2;

  const centralAngle =
    2 * Math.atan2(Math.sqrt(haversine), Math.sqrt(1 - haversine));

  return EARTH_RADIUS_METERS * centralAngle;
}

/** True when two reported locations are within the allowed verification radius. */
export function isWithinDistance(
  from: Coordinates,
  to: Coordinates,
  thresholdMeters = DEFAULT_LOCATION_THRESHOLD_METERS,
): boolean {
  if (thresholdMeters < 0) {
    throw new Error("Distance threshold must be non-negative");
  }

  return haversineDistanceMeters(from, to) <= thresholdMeters;
}

/**
 * Combined location verification used during the second-factor step:
 * HMAC must match and the reported point must be near the login point.
 */
export function verifyLocationAttestation(options: {
  loginLocation: Coordinates;
  verificationLocation: Coordinates;
  payload: LocationHmacPayload;
  secret: string;
  expectedHmac: string;
  thresholdMeters?: number;
}): { valid: boolean; distanceMeters: number; hmacValid: boolean; withinRange: boolean } {
  const hmacValid = verifyLocationHmac(
    options.payload,
    options.secret,
    options.expectedHmac,
  );
  const distanceMeters = haversineDistanceMeters(
    options.loginLocation,
    options.verificationLocation,
  );
  const withinRange = distanceMeters <= (options.thresholdMeters ?? DEFAULT_LOCATION_THRESHOLD_METERS);

  return {
    valid: hmacValid && withinRange,
    distanceMeters,
    hmacValid,
    withinRange,
  };
}

/** URL-safe opaque token for one-time email verification links. */
export function generateUrlKey(byteLength = 32): string {
  return randomBytes(byteLength).toString("base64url");
}
