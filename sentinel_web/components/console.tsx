"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  Aperture,
  Camera as CameraIcon,
  Check,
  ChevronRight,
  CircleHelp,
  Clock3,
  Grid2X2,
  HardDrive,
  Maximize2,
  Monitor,
  PawPrint,
  Radio,
  RefreshCw,
  Search,
  Settings2,
  Shield,
  SlidersHorizontal,
  Upload,
  Wifi,
  X,
} from "lucide-react";
import { cameras, type Camera } from "@/lib/cameras";
import { Player } from "./player";
import { Snapshot } from "./snapshot";
import { Animals, type AnimalHealth } from "./animals";
import { IvsecEvents } from "./ivsec-events";
type Tab = "live" | "animals" | "playback" | "system";
type Health = {
  configured: boolean;
  host: string;
  metadataSource: string;
  animals: AnimalHealth | null;
};
const navigation = [
  { id: "live" as const, label: "Live view", icon: Grid2X2 },
  { id: "animals" as const, label: "Animals", icon: PawPrint },
  { id: "playback" as const, label: "Playback", icon: Clock3 },
  { id: "system" as const, label: "System", icon: Settings2 },
];
export function Console() {
  const [tab, setTab] = useState<Tab>("live");
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [zone, setZone] = useState("All cameras");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Camera | null>(null);
  const [streamState, setStreamState] = useState("Connecting");
  const [showInactive, setShowInactive] = useState(true);
  const [snapshotTick, setSnapshotTick] = useState(() => Date.now());
  const [localClip, setLocalClip] = useState<{
    url: string;
    name: string;
  } | null>(null);
  const [clipError, setClipError] = useState(false);
  const [time, setTime] = useState("LOCAL NETWORK");
  const [refreshing, setRefreshing] = useState(true);
  const dialog = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const updateStream = useCallback(
    (state: string) => setStreamState(state),
    [],
  );
  const refresh = useCallback(async () => {
    try {
      const response = await fetch("/api/health");
      if (!response.ok) throw new Error();
      setHealth(await response.json());
      setHealthError(false);
    } catch {
      setHealthError(true);
    } finally {
      setRefreshing(false);
    }
  }, []);
  useEffect(() => {
    // Health state is updated only after the asynchronous network request resolves.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
    const requestedTab = new URLSearchParams(window.location.search).get("tab");
    if (requestedTab === "animals") setTab("animals");
    const timer = setInterval(() => {
      setTime(new Date().toLocaleTimeString("en-AU", { hour12: false }));
      if (!document.hidden) setSnapshotTick(Date.now());
    }, 1000);
    return () => clearInterval(timer);
  }, [refresh]);
  useEffect(() => {
    if (selected) dialog.current?.showModal();
    else {
      dialog.current?.close();
      opener.current?.focus();
    }
  }, [selected]);
  useEffect(
    () => () => {
      if (localClip) URL.revokeObjectURL(localClip.url);
    },
    [localClip],
  );
  const filtered = cameras.filter(
    (c) =>
      (showInactive || c.seen) &&
      (zone === "All cameras" || c.zone === zone) &&
      c.name.toLowerCase().includes(search.toLowerCase()),
  );
  function openCamera(camera: Camera) {
    opener.current = document.activeElement as HTMLElement;
    setStreamState("Connecting");
    setSelected(camera);
  }
  return (
    <div className="shell">
      <aside className="sidebar">
        <Link className="brand" href="/" aria-label="Sentinel home">
          <span className="brand-icon">
            <Aperture size={27} />
          </span>
          <span>
            SENTINEL<i>RESIDENTIAL SECURITY OS</i>
          </span>
        </Link>
        <div className="side-caption">WORKSPACE / 01</div>
        <nav aria-label="Main navigation">
          {navigation.map((item) => (
            <button
              key={item.id}
              className={tab === item.id ? "nav-item active" : "nav-item"}
              onClick={() => setTab(item.id)}
            >
              <item.icon size={19} />
              {item.label}
              <span>
                {item.id === "live" ? "08" : <ChevronRight size={14} />}
              </span>
            </button>
          ))}
        </nav>
        <div className="side-bottom">
          <div className="network-symbol">
            <Shield size={23} />
          </div>
          <strong>
            Your perimeter.
            <br />
            Your control.
          </strong>
          <p>
            Private infrastructure.
            <br />
            Always on your network.
          </p>
          <div className="local-tag">
            <span /> LOCAL ACCESS
          </div>
          <small>
            SENTINEL OS <b>v0.1.0</b>
          </small>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="mobile-brand">
            <Aperture size={23} /> SENTINEL
          </div>
          <div className="breadcrumb">
            WORKSPACE <ChevronRight size={12} />
            <span>HOME SECURITY</span>
          </div>
          <div className="top-right">
            <span className="network-label">
              <Wifi size={14} /> LOCAL NETWORK
            </span>
            <span className="time">{time}</span>
            <span className="avatar">IS</span>
          </div>
        </header>
        <main>
          {(tab === "playback" || tab === "system") && (
            <div className="page-heading">
              <div>
                <div className="eyebrow">
                  <span /> SENTINEL COMMAND CENTER
                </div>
                <h1>
                  {tab === "playback" ? (
                    <>
                      Revisit <em>the moment.</em>
                    </>
                  ) : (
                    <>
                      Control <em>your perimeter.</em>
                    </>
                  )}
                </h1>
                <p>
                  {tab === "playback"
                    ? "Review footage and find what matters."
                    : "Your recorder, connections, and camera inventory."}
                </p>
              </div>
              <button
                className="refresh-button"
                onClick={() => {
                  setRefreshing(true);
                  void refresh();
                }}
                disabled={refreshing}
              >
                <RefreshCw size={15} className={refreshing ? "spin" : ""} />
                <span>{refreshing ? "Checking…" : "Check connection"}</span>
              </button>
            </div>
          )}
          {(tab === "playback" || tab === "system") && (
            <section className="stats" aria-label="System overview">
              <div>
                <span className="stat-icon">
                  <CameraIcon size={19} />
                </span>
                <div>
                  <label>CAMERA INVENTORY</label>
                  <strong>
                    06 <small>/ configured</small>
                  </strong>
                </div>
                <span className="stat-end">↗</span>
              </div>
              <div>
                <span className="stat-icon cyan">
                  <Radio size={19} />
                </span>
                <div>
                  <label>STREAM BRIDGE</label>
                  <strong className="status-text">
                    {healthError
                      ? "Unreachable"
                      : health?.configured
                        ? "Configured"
                        : health
                          ? "Setup required"
                          : "Checking…"}
                  </strong>
                </div>
                <span
                  className={`dot ${health?.configured ? "cyan-dot" : ""}`}
                />
              </div>
              <div>
                <span className="stat-icon">
                  <HardDrive size={19} />
                </span>
                <div>
                  <label>LOCAL RECORDER</label>
                  <strong className="status-text">
                    IVSEC <small>NR16</small>
                  </strong>
                </div>
                <span className="device-detail">16 CH</span>
              </div>
            </section>
          )}
          {tab === "live" && (
            <>
              <div className="live-summary">
                <div>
                  <h1>Live cameras</h1>
                  <span className="live-status">
                    <span className={health?.configured ? "online" : ""} />
                    {healthError
                      ? "Bridge unavailable"
                      : health?.configured
                        ? "1-second snapshots active"
                        : "Stream bridge needs setup"}
                  </span>
                </div>
                <button
                  className="refresh-button"
                  aria-label="Refresh connection status"
                  onClick={() => {
                    setRefreshing(true);
                    void refresh();
                    setSnapshotTick(Date.now());
                  }}
                  disabled={refreshing}
                >
                  <RefreshCw size={15} className={refreshing ? "spin" : ""} />
                </button>
              </div>
              <div className="section-top">
                <div>
                  <h2>
                    <span className="slash">{"//"}</span> Camera feeds{" "}
                    <span className="count">
                      {filtered.length.toString().padStart(2, "0")}
                    </span>
                  </h2>
                  <p>Tap any camera for live video.</p>
                </div>
                <span className="view-label">
                  <Grid2X2 size={15} /> GRID VIEW
                </span>
              </div>
              <div className="toolbar">
                <div className="filters">
                  {["All cameras", "Entry", "Outdoor"].map((item) => (
                    <button
                      className={zone === item ? "selected" : ""}
                      onClick={() => setZone(item)}
                      key={item}
                    >
                      {item}
                    </button>
                  ))}
                </div>
                <div className="search-wrap">
                  <Search size={15} />
                  <input
                    aria-label="Search cameras"
                    placeholder="Find a camera…"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                </div>
                <button
                  className={`filter-toggle ${showInactive ? "on" : ""}`}
                  aria-label="Include previously offline cameras"
                  title="Include previously offline cameras"
                  aria-pressed={showInactive}
                  onClick={() => setShowInactive((v) => !v)}
                >
                  <SlidersHorizontal size={17} />
                </button>
              </div>
              <div className="camera-grid">
                {filtered.map((camera) => (
                  <button
                    key={camera.id}
                    className={`camera-card scene-${camera.id}`}
                    onClick={() => openCamera(camera)}
                  >
                    <div className="camera-visual">
                      <div className="camera-top">
                        <span className="channel">CH {camera.id}</span>
                        {!camera.seen && (
                          <span className="feed-state">
                            <span /> PREVIOUSLY OFFLINE
                          </span>
                        )}
                      </div>
                      <div className="scene" aria-hidden="true">
                        <div className="building b1" />
                        <div className="building b2" />
                        <div className="building b3" />
                        <div className="ground" />
                        <div className="crosshair" />
                      </div>
                      <Snapshot
                        channel={camera.id}
                        name={camera.name}
                        tick={snapshotTick}
                        enabled={Boolean(health?.configured && camera.seen)}
                      />
                      <div className="camera-bottom">
                        <span>
                          SECTOR {camera.id} / {camera.zone.toUpperCase()}
                        </span>
                        <Maximize2 size={14} />
                      </div>
                    </div>
                    <div className="camera-info">
                      <div>
                        <h3>{camera.name}</h3>
                        <p>
                          <span className="tiny-dot" />
                          {camera.seen
                            ? "Refreshing every second"
                            : "Offline in last inspection"}
                        </p>
                      </div>
                      <ArrowUpRight size={19} />
                    </div>
                  </button>
                ))}
              </div>
              {filtered.length === 0 && (
                <div className="empty">
                  <Search />
                  <h3>No matching cameras</h3>
                  <p>Try another name or camera group.</p>
                </div>
              )}
              <div className="inventory-note">
                <CircleHelp size={15} />
                <span>
                  Snapshots refresh every second. Tap a tile for live video.
                </span>
              </div>
              {!health?.configured && (
                <div className="connection-banner">
                  <div className="banner-icon">
                    <Wifi size={24} />
                  </div>
                  <div>
                    <h3>
                      {health?.configured
                        ? "Ready to make contact."
                        : "Your cameras are one connection away."}
                    </h3>
                    <p>
                      {health?.configured
                        ? "Open a feed to verify live video from your local recorder."
                        : "Add your IVSEC credentials on the host to bring your feeds online."}
                    </p>
                  </div>
                  <button onClick={() => setTab("system")}>
                    {health?.configured ? "View system" : "Connection setup"}
                    <ArrowUpRight size={16} />
                  </button>
                </div>
              )}
            </>
          )}
          {tab === "playback" && (
            <section className="playback-layout">
              <div className="panel">
                <div className="panel-heading">
                  <h2>
                    <span className="slash">{"//"}</span> Footage review
                  </h2>
                  <span className="tag">LOCAL FILE</span>
                </div>
                <div className="clip-view">
                  {localClip ? (
                    <video
                      key={localClip.url}
                      src={localClip.url}
                      controls
                      playsInline
                      onError={() => setClipError(true)}
                    />
                  ) : (
                    <div className="empty">
                      <Clock3 size={40} />
                      <h3>A moment worth a closer look.</h3>
                      <p>
                        Open an exported recording from your device.
                        <br />
                        Your video stays in this browser.
                      </p>
                    </div>
                  )}
                </div>
                {clipError && (
                  <p className="notice">
                    This export uses an unsupported codec. Try an H.264 MP4
                    export.
                  </p>
                )}
                <div className="upload-row">
                  <span>
                    {localClip?.name || "MP4 / browser-compatible video"}
                  </span>
                  <label className="primary upload">
                    <Upload size={16} /> Open recording
                    <input
                      type="file"
                      accept="video/*,.mp4"
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (file) {
                          setLocalClip({
                            url: URL.createObjectURL(file),
                            name: file.name,
                          });
                          setClipError(false);
                        }
                      }}
                    />
                  </label>
                </div>
              </div>
              <IvsecEvents onOpenCamera={openCamera} />
            </section>
          )}
          {tab === "animals" && (
            <Animals health={health?.animals || null} onOpenCamera={openCamera} />
          )}
          {tab === "system" && (
            <>
              <div className="system-grid">
                <section className="panel">
                  <div className="panel-heading">
                    <h2>
                      <span className="slash">{"//"}</span> Connection
                    </h2>
                    <span className="tag">LOCAL HOST</span>
                  </div>
                  <dl>
                    <div>
                      <dt>Recorder</dt>
                      <dd>{health?.host || "192.168.68.203"}</dd>
                    </div>
                    <div>
                      <dt>Model / firmware *</dt>
                      <dd>NR16-9000-4TB / 8.2.4.1</dd>
                    </div>
                    <div>
                      <dt>Video delivery</dt>
                      <dd>RTSP → H.264 / HLS</dd>
                    </div>
                    <div>
                      <dt>Credentials</dt>
                      <dd
                        className={
                          health?.configured ? "cyan-text" : "yellow-text"
                        }
                      >
                        {health?.configured
                          ? "Configured on host"
                          : "Not configured"}
                      </dd>
                    </div>
                    <div>
                      <dt>Animal detector</dt>
                      <dd
                        className={
                          health?.animals?.frigateOnline
                            ? "cyan-text"
                            : "yellow-text"
                        }
                      >
                        {health?.animals?.frigateOnline
                          ? `${health.animals.model} / ${health.animals.provider}`
                          : "Offline"}
                      </dd>
                    </div>
                    <div>
                      <dt>Animal event bus</dt>
                      <dd
                        className={
                          health?.animals?.mqttOnline
                            ? "cyan-text"
                            : "yellow-text"
                        }
                      >
                        {health?.animals?.mqttOnline
                          ? "Connected"
                          : "Unavailable"}
                      </dd>
                    </div>
                  </dl>
                  <p className="muted">
                    * Saved device details from 30 Mar 2026. This screen does
                    not query current recorder configuration.
                  </p>
                  <button
                    className="secondary"
                    onClick={() => {
                      setRefreshing(true);
                      void refresh();
                    }}
                  >
                    <RefreshCw size={15} /> Recheck host configuration
                  </button>
                  {healthError && (
                    <p role="alert" className="notice">
                      Unable to reach the Sentinel server.
                    </p>
                  )}
                </section>
                <section className="panel setup">
                  <div className="panel-heading">
                    <h2>
                      <span className="slash">{"//"}</span> Bring it online
                    </h2>
                    <Monitor size={19} />
                  </div>
                  <ol>
                    <li>
                      <b>Set the recorder credentials</b>
                      <span>
                        Copy .env.example to .env.local on your Linux host. Fill
                        in IVSEC_USERNAME and IVSEC_PASSWORD.
                      </span>
                    </li>
                    <li>
                      <b>Start the video bridge</b>
                      <span>
                        Install FFmpeg or use the included Docker Compose setup.
                        The bridge starts when you open a camera.
                      </span>
                    </li>
                    <li>
                      <b>Connect from your iPhone</b>
                      <span>
                        Open the Linux computer’s address on port 3000 while
                        connected to your local network.
                      </span>
                    </li>
                  </ol>
                  <div className="setup-footer">
                    <Shield size={16} /> Credentials stay on the server.
                  </div>
                </section>
              </div>
              <section className="panel inventory">
                <div className="panel-heading">
                  <h2>
                    <span className="slash">{"//"}</span> Channel inventory
                  </h2>
                  <span className="tag">SAVED SNAPSHOT</span>
                </div>
                {cameras.map((camera) => (
                  <div className="inventory-row" key={camera.id}>
                    <span className="inventory-id">{camera.id}</span>
                    <div>
                      <strong>{camera.name}</strong>
                      <small>{camera.zone}</small>
                    </div>
                    <span
                      className={
                        camera.seen ? "snapshot-online" : "snapshot-offline"
                      }
                    >
                      {camera.seen ? <Check size={13} /> : <X size={13} />}{" "}
                      {camera.seen ? "Previously online" : "Previously offline"}
                    </span>
                    <button
                      aria-label={`Open ${camera.name}`}
                      onClick={() => openCamera(camera)}
                    >
                      <ArrowUpRight size={18} />
                    </button>
                  </div>
                ))}
                <p className="muted">
                  Channels 9–10 were reported offline; 11–16 were not
                  classified. Device settings and ONVIF events are reserved for
                  a future integration.
                </p>
              </section>
            </>
          )}
          <footer>
            <span>
              <Aperture size={13} /> SENTINEL / PRIVATE BY DESIGN
            </span>
            <span>
              LOCAL INFRASTRUCTURE <span className="yellow-text">↗</span>
            </span>
          </footer>
        </main>
      </div>
      <nav className="bottom-nav" aria-label="Mobile navigation">
        {navigation.map((item) => (
          <button
            key={item.id}
            className={tab === item.id ? "active" : ""}
            onClick={() => setTab(item.id)}
          >
            <item.icon size={20} />
            <span>{item.label}</span>
          </button>
        ))}
      </nav>
      <dialog
        className="camera-dialog"
        ref={dialog}
        onCancel={() => setSelected(null)}
        onClick={(e) => {
          if (e.target === dialog.current) setSelected(null);
        }}
        aria-labelledby="stream-title"
      >
        <div className="dialog-header">
          <div>
            <span className="eyebrow">
              CH {selected?.id} / {streamState.toUpperCase()}
            </span>
            <h2 id="stream-title">{selected?.name}</h2>
          </div>
          <button
            autoFocus
            aria-label="Close camera"
            onClick={() => setSelected(null)}
          >
            <X />
          </button>
        </div>
        <div className="dialog-footer">
          <span>
            <Radio size={14} /> {streamState}
          </span>
          <span>720p / video only · a few seconds behind real time</span>
        </div>
        {selected && (
          <Player
            key={selected.id}
            channel={selected.id}
            onState={updateStream}
          />
        )}
      </dialog>
    </div>
  );
}
