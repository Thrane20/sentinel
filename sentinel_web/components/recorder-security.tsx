"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ShieldCheck,
  ShieldOff,
  ShieldQuestion,
  RefreshCw,
} from "lucide-react";

type RecorderState = {
  online: boolean;
  disarming: boolean;
  armed: boolean;
  checkedAt: number;
};

export function RecorderSecurity() {
  const [state, setState] = useState<RecorderState | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const writing = useRef(false);
  const pending = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    if (writing.current || pending.current) return;
    const current = ++generation.current;
    const controller = new AbortController();
    pending.current = controller;
    try {
      const response = await fetch("/api/ivsec/security", {
        cache: "no-store",
        signal: AbortSignal.any([
          controller.signal,
          AbortSignal.timeout(25000),
        ]),
      });
      const body = await response.json();
      if (!response.ok || !body.online || typeof body.disarming !== "boolean")
        throw new Error(body.error || "IVSEC status unavailable.");
      if (current === generation.current) {
        setState(body);
        setError("");
      }
    } catch (cause) {
      if (current === generation.current && !controller.signal.aborted) {
        setState(null);
        setError(
          cause instanceof Error ? cause.message : "IVSEC status unavailable.",
        );
      }
    } finally {
      if (pending.current === controller) pending.current = null;
      if (current === generation.current) setLoaded(true);
    }
  }, []);

  useEffect(() => {
    const requestGeneration = generation;
    // The recorder read updates state only after its asynchronous response.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
    const timer = setInterval(() => void refresh(), 10000);
    const onFocus = () => void refresh();
    window.addEventListener("focus", onFocus);
    return () => {
      clearInterval(timer);
      window.removeEventListener("focus", onFocus);
      ++requestGeneration.current;
      pending.current?.abort();
      pending.current = null;
    };
  }, [refresh]);

  async function toggle() {
    if (!state || writing.current) return;
    writing.current = true;
    ++generation.current;
    pending.current?.abort();
    pending.current = null;
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/ivsec/security", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          disarming: !state.disarming,
          expectedDisarming: state.disarming,
        }),
        signal: AbortSignal.timeout(45000),
      });
      const body = await response.json();
      if (!response.ok || !body.online || body.disarming !== !state.disarming)
        throw new Error(
          body.error || "IVSEC did not confirm the requested state.",
        );
      setState(body);
    } catch (cause) {
      setState(null);
      setError(
        cause instanceof Error
          ? cause.message
          : "IVSEC did not confirm the change.",
      );
    } finally {
      writing.current = false;
      setBusy(false);
      setLoaded(true);
    }
  }

  const status = state ? (state.disarming ? "disarmed" : "armed") : "unknown";
  const Icon = state
    ? state.disarming
      ? ShieldOff
      : ShieldCheck
    : ShieldQuestion;
  return (
    <div className="recorder-security" aria-label="IVSEC arming controls">
      <span className={`recorder-arm-status ${status}`} role="status">
        <Icon size={15} aria-hidden="true" />
        {state
          ? state.disarming
            ? "Disarmed"
            : "Armed"
          : loaded
            ? "Status unavailable"
            : "Checking IVSEC…"}
      </span>
      {state ? (
        <button
          className={`recorder-arm-toggle ${status}`}
          disabled={busy}
          onClick={() => void toggle()}
        >
          {busy
            ? "Updating IVSEC…"
            : state.disarming
              ? "Arm IVSEC"
              : "Disarm IVSEC"}
        </button>
      ) : loaded ? (
        <button
          className="recorder-arm-toggle"
          onClick={() => void refresh()}
          aria-label="Refresh IVSEC arming status"
        >
          <RefreshCw size={13} /> Retry
        </button>
      ) : null}
      {error && (
        <span className="recorder-arm-error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
