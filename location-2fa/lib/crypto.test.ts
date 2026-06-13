import { describe, expect, it } from "vitest";

import {
  DEFAULT_LOCATION_THRESHOLD_METERS,
  createLocationHmac,
  generateUrlKey,
  haversineDistanceMeters,
  isWithinDistance,
  normalizeCoordinates,
  serializeLocationPayload,
  verifyLocationAttestation,
  verifyLocationHmac,
  type LocationHmacPayload,
} from "./crypto";

const SECRET = "test-hmac-secret";
const BASE_PAYLOAD: LocationHmacPayload = {
  latitude: 37.774929,
  longitude: -122.419416,
  sessionId: "session-123",
  timestamp: 1_700_000_000_000,
};

describe("normalizeCoordinates", () => {
  it("rounds coordinates to the configured precision", () => {
    expect(
      normalizeCoordinates({
        latitude: 37.7749295123,
        longitude: -122.419416789,
      }),
    ).toEqual({
      latitude: 37.77493,
      longitude: -122.419417,
    });
  });
});

describe("serializeLocationPayload", () => {
  it("creates a stable pipe-delimited payload string", () => {
    expect(serializeLocationPayload(BASE_PAYLOAD)).toBe(
      "37.774929|-122.419416|session-123|1700000000000",
    );
  });
});

describe("createLocationHmac", () => {
  it("returns a deterministic hex digest for the same payload", () => {
    const first = createLocationHmac(BASE_PAYLOAD, SECRET);
    const second = createLocationHmac(BASE_PAYLOAD, SECRET);

    expect(first).toBe(second);
    expect(first).toMatch(/^[a-f0-9]{64}$/);
  });

  it("changes when coordinates or session metadata change", () => {
    const baseline = createLocationHmac(BASE_PAYLOAD, SECRET);
    const moved = createLocationHmac(
      { ...BASE_PAYLOAD, latitude: 37.775 },
      SECRET,
    );
    const differentSession = createLocationHmac(
      { ...BASE_PAYLOAD, sessionId: "session-456" },
      SECRET,
    );

    expect(moved).not.toBe(baseline);
    expect(differentSession).not.toBe(baseline);
  });

  it("requires a secret", () => {
    expect(() => createLocationHmac(BASE_PAYLOAD, "")).toThrow(
      "HMAC secret is required",
    );
  });
});

describe("verifyLocationHmac", () => {
  it("accepts a matching digest", () => {
    const digest = createLocationHmac(BASE_PAYLOAD, SECRET);

    expect(verifyLocationHmac(BASE_PAYLOAD, SECRET, digest)).toBe(true);
  });

  it("rejects tampered coordinates or digests", () => {
    const digest = createLocationHmac(BASE_PAYLOAD, SECRET);

    expect(
      verifyLocationHmac(
        { ...BASE_PAYLOAD, longitude: -122.5 },
        SECRET,
        digest,
      ),
    ).toBe(false);
    expect(verifyLocationHmac(BASE_PAYLOAD, SECRET, `${digest.slice(0, -1)}a`)).toBe(
      false,
    );
    expect(verifyLocationHmac(BASE_PAYLOAD, SECRET, "")).toBe(false);
  });
});

describe("haversineDistanceMeters", () => {
  it("returns zero for identical coordinates", () => {
    const point = { latitude: 40.7128, longitude: -74.006 };

    expect(haversineDistanceMeters(point, point)).toBe(0);
  });

  it("matches a known San Francisco to Oakland distance", () => {
    const sanFrancisco = { latitude: 37.7749, longitude: -122.4194 };
    const oakland = { latitude: 37.8044, longitude: -122.2712 };
    const distance = haversineDistanceMeters(sanFrancisco, oakland);

    expect(distance).toBeGreaterThan(12_000);
    expect(distance).toBeLessThan(14_000);
  });
});

describe("isWithinDistance", () => {
  it("accepts nearby points within the default threshold", () => {
    const login = { latitude: 37.7749, longitude: -122.4194 };
    const verification = { latitude: 37.7752, longitude: -122.4198 };

    expect(isWithinDistance(login, verification)).toBe(true);
  });

  it("rejects points beyond the threshold", () => {
    const login = { latitude: 37.7749, longitude: -122.4194 };
    const verification = { latitude: 37.8044, longitude: -122.2712 };

    expect(
      isWithinDistance(login, verification, DEFAULT_LOCATION_THRESHOLD_METERS),
    ).toBe(false);
  });

  it("rejects negative thresholds", () => {
    expect(() =>
      isWithinDistance(
        { latitude: 0, longitude: 0 },
        { latitude: 0, longitude: 0 },
        -1,
      ),
    ).toThrow("Distance threshold must be non-negative");
  });
});

describe("verifyLocationAttestation", () => {
  it("passes when HMAC and distance checks succeed", () => {
    const loginLocation = { latitude: 37.7749, longitude: -122.4194 };
    const verificationLocation = { latitude: 37.7751, longitude: -122.4196 };
    const payload: LocationHmacPayload = {
      ...verificationLocation,
      sessionId: BASE_PAYLOAD.sessionId,
      timestamp: BASE_PAYLOAD.timestamp,
    };
    const expectedHmac = createLocationHmac(payload, SECRET);

    const result = verifyLocationAttestation({
      loginLocation,
      verificationLocation,
      payload,
      secret: SECRET,
      expectedHmac,
    });

    expect(result.valid).toBe(true);
    expect(result.hmacValid).toBe(true);
    expect(result.withinRange).toBe(true);
    expect(result.distanceMeters).toBeLessThan(100);
  });

  it("fails when the HMAC is valid but the user moved too far", () => {
    const loginLocation = { latitude: 37.7749, longitude: -122.4194 };
    const verificationLocation = { latitude: 37.8044, longitude: -122.2712 };
    const payload: LocationHmacPayload = {
      ...verificationLocation,
      sessionId: BASE_PAYLOAD.sessionId,
      timestamp: BASE_PAYLOAD.timestamp,
    };
    const expectedHmac = createLocationHmac(payload, SECRET);

    const result = verifyLocationAttestation({
      loginLocation,
      verificationLocation,
      payload,
      secret: SECRET,
      expectedHmac,
    });

    expect(result.valid).toBe(false);
    expect(result.hmacValid).toBe(true);
    expect(result.withinRange).toBe(false);
  });
});

describe("generateUrlKey", () => {
  it("returns URL-safe opaque tokens", () => {
    const token = generateUrlKey();

    expect(token.length).toBeGreaterThan(20);
    expect(token).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(generateUrlKey()).not.toBe(token);
  });
});
