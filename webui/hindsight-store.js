import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";
import { toastFrontendError, toastFrontendSuccess } from "/components/notifications/notification-store.js";

const DEFAULT_DRAFT = {
  hindsight_agent_memory_enabled: false,
  hindsight_agent_bank_id: "",
  hindsight_agent_retain_to_project: false,
};

function cloneSettings(settings = {}) {
  return {
    hindsight_agent_memory_enabled: !!settings.hindsight_agent_memory_enabled,
    hindsight_agent_bank_id: settings.hindsight_agent_bank_id || "",
    hindsight_agent_retain_to_project: !!settings.hindsight_agent_retain_to_project,
  };
}

export const store = createStore("a0Hindsight", {
  visible: false,
  loading: false,
  saving: false,
  ctxid: "",
  projectName: "",
  agentProfile: "agent0",
  projectBankId: "",
  agentBankId: "",
  retainBankIds: [],
  recallBankIds: [],
  settings: { ...DEFAULT_DRAFT },
  draft: { ...DEFAULT_DRAFT },
  liftEls: [],
  outputEl: null,
  hostEl: null,
  resizeListener: null,
  resizeRaf: 0,

  onContextChanged(ctxid) {
    const next = ctxid || "";
    if (next && next !== this.ctxid) {
      this.ctxid = next;
      if (this.visible) this.refresh({ force: true });
    }
  },

  anchor() { return document.querySelector(".a0-hindsight-tab-anchor"); },
  button() { return document.querySelector(".a0-hindsight-tab-anchor > .text-button"); },
  actionHost() {
    const anchor = this.anchor();
    if (!anchor) return null;
    return anchor.closest?.(".chat-bottom-actions-bar") || anchor.closest?.(".text-buttons-row") || anchor.parentElement || anchor;
  },

  composerReferenceEl(host) {
    const input = document.getElementById("chat-input");
    const row = input?.closest?.(".input-row");
    if (row && !(host && (row === host || host.contains(row)))) return row;
    const container = input?.closest?.("#chat-input-container");
    if (container && !(host && (container === host || host.contains(container)))) return container;
    return input || null;
  },

  composerLiftTargets(host) {
    const targets = [];
    const add = (el) => {
      if (!el || targets.includes(el)) return;
      if (host && (el === host || host.contains(el))) return;
      if (el.closest?.(".chat-bottom-actions-bar") || el.classList?.contains("chat-bottom-actions-bar")) return;
      targets.push(el);
    };
    const progressBox = document.getElementById("progress-bar-box");
    add(progressBox);
    add(this.composerReferenceEl(host));
    return targets;
  },

  liftComposerElements(host, lift) {
    const targets = this.composerLiftTargets(host);
    for (const previous of this.liftEls || []) {
      if (!targets.includes(previous)) {
        previous.classList.remove("a0-hindsight-compose-lifted");
        previous.style.removeProperty("--a0-hindsight-panel-lift");
      }
    }
    this.liftEls = targets;
    for (const el of targets) {
      el.style.setProperty("--a0-hindsight-panel-lift", `${lift}px`);
      el.classList.add("a0-hindsight-compose-lifted");
    }
  },

  clearComposerLift() {
    for (const el of this.liftEls || []) {
      el.classList.remove("a0-hindsight-compose-lifted");
      el.style.removeProperty("--a0-hindsight-panel-lift");
    }
    this.liftEls = [];
  },

  outputHost(host) {
    try {
      const history = document.getElementById("chat-history");
      if (history) return history;
      const hostRect = host?.getBoundingClientRect?.();
      if (!hostRect) return null;
      const candidates = Array.from(document.querySelectorAll('[data-role="messages"], .messages, .message-list, .chat-messages, .monologue, main, section'));
      let best = null;
      let bestScore = -Infinity;
      for (const el of candidates) {
        if (!el || el === host || host.contains(el) || el.contains(host)) continue;
        const rect = el.getBoundingClientRect();
        if (rect.width < 260 || rect.height < 160) continue;
        if (rect.bottom > hostRect.top + 24) continue;
        if (rect.right < hostRect.left + 80 || rect.left > hostRect.right - 80) continue;
        const style = window.getComputedStyle(el);
        const canScroll = /(auto|scroll)/.test(`${style.overflowY} ${style.overflow}`) || el.scrollHeight > el.clientHeight + 24;
        const verticalCloseness = Math.max(0, 420 - Math.abs(hostRect.top - rect.bottom));
        const widthOverlap = Math.min(rect.right, hostRect.right) - Math.max(rect.left, hostRect.left);
        const score = (canScroll ? 1000 : 0) + verticalCloseness + Math.max(0, widthOverlap) - Math.abs(rect.width - hostRect.width) * 0.15;
        if (score > bestScore) {
          bestScore = score;
          best = el;
        }
      }
      return best;
    } catch (_e) {
      return null;
    }
  },

  lowerChromeTop(host) {
    try {
      const hostRect = host?.getBoundingClientRect?.();
      const inputSection = document.getElementById("input-section");
      const progressBox = document.getElementById("progress-bar-box");
      const candidates = [progressBox, inputSection, host].filter(Boolean);
      let top = Number.POSITIVE_INFINITY;
      for (const el of candidates) {
        const rect = el.getBoundingClientRect();
        if (!rect || rect.height <= 0) continue;
        if (rect.bottom < 0) continue;
        top = Math.min(top, rect.top);
      }
      if (Number.isFinite(top)) return Math.round(top);
      return Math.round(hostRect?.top || 0);
    } catch (_e) {
      return 0;
    }
  },

  liftOutputHost(host, lift) {
    try {
      const output = this.outputHost(host);
      if (this.outputEl && this.outputEl !== output) this.clearOutputLift();
      if (!output) return;
      this.outputEl = output;
      output.classList.add("a0-hindsight-output-lifted");
      if (!output.dataset.a0HindsightHasOriginals) {
        const computed = window.getComputedStyle(output);
        output.dataset.a0HindsightHasOriginals = "1";
        output.dataset.a0HindsightOriginalHeight = output.style.height || "";
        output.dataset.a0HindsightOriginalMaxHeight = output.style.maxHeight || "";
        output.dataset.a0HindsightOriginalPaddingBottom = output.style.paddingBottom || "";
        output.dataset.a0HindsightOriginalMarginBottom = output.style.marginBottom || "";
        output.dataset.a0HindsightBasePaddingBottom = String(Number.parseFloat(computed.paddingBottom) || 0);
        output.dataset.a0HindsightBaseHeight = String(output.getBoundingClientRect().height || output.clientHeight || 0);
      }
      const rect = output.getBoundingClientRect();
      const lowerTop = this.lowerChromeTop(host);
      const desiredBottom = Math.max(0, lowerTop - 2);
      const targetHeightFromGeometry = Math.max(140, Math.round(desiredBottom - rect.top));
      const baseHeight = Number.parseFloat(output.dataset.a0HindsightBaseHeight || "0") || rect.height || output.clientHeight || targetHeightFromGeometry;
      const targetHeight = Math.min(Math.round(baseHeight), targetHeightFromGeometry);
      const basePadding = Number.parseFloat(output.dataset.a0HindsightBasePaddingBottom || "0") || 0;
      output.style.height = `${targetHeight}px`;
      output.style.maxHeight = `${targetHeight}px`;
      output.style.paddingBottom = `${Math.round(basePadding + Math.max(0, lift * 0.25))}px`;
      output.style.marginBottom = "0px";
      if (typeof output.scrollTop === "number") output.scrollTop = output.scrollTop;
    } catch (_e) {}
  },

  clearOutputLift() {
    if (!this.outputEl) return;
    const output = this.outputEl;
    output.classList.remove("a0-hindsight-output-lifted");
    output.style.height = output.dataset.a0HindsightOriginalHeight || "";
    output.style.maxHeight = output.dataset.a0HindsightOriginalMaxHeight || "";
    output.style.paddingBottom = output.dataset.a0HindsightOriginalPaddingBottom || "";
    output.style.marginBottom = output.dataset.a0HindsightOriginalMarginBottom || "";
    delete output.dataset.a0HindsightHasOriginals;
    delete output.dataset.a0HindsightOriginalHeight;
    delete output.dataset.a0HindsightOriginalMaxHeight;
    delete output.dataset.a0HindsightOriginalPaddingBottom;
    delete output.dataset.a0HindsightOriginalMarginBottom;
    delete output.dataset.a0HindsightBasePaddingBottom;
    delete output.dataset.a0HindsightBaseHeight;
    this.outputEl = null;
  },

  syncPanelPlacement() {
    try {
      const anchor = this.anchor();
      const button = this.button();
      const host = this.actionHost();
      if (!anchor || !button || !host) return;
      if (this.hostEl && this.hostEl !== host) {
        this.hostEl.classList.remove("a0-hindsight-host-lifted");
        this.hostEl.style.removeProperty("--a0-hindsight-panel-lift");
      }
      this.hostEl = host;

      const hostRect = host.getBoundingClientRect();
      const buttonRect = button.getBoundingClientRect();
      const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 800;
      const marginValue = getComputedStyle(anchor).getPropertyValue("--a0-hindsight-panel-margin").trim();
      const margin = Number.parseFloat(marginValue) || 8;
      const anchorRect = anchor.getBoundingClientRect();
      const reference = this.composerReferenceEl(host);
      const referenceRect = reference?.getBoundingClientRect?.();
      const activeReferenceLift = reference
        ? (Number.parseFloat(reference.style.getPropertyValue("--a0-hindsight-panel-lift")) ||
          Number.parseFloat(getComputedStyle(reference).getPropertyValue("--a0-hindsight-panel-lift")) || 0)
        : 0;
      const panelBottom = Math.round(anchorRect.top || buttonRect.top || hostRect.top);
      const referenceUnliftedBottom = referenceRect ? Math.round(referenceRect.bottom + activeReferenceLift) : null;
      const originalComposerGap = referenceUnliftedBottom !== null ? Math.max(0, Math.round(panelBottom - referenceUnliftedBottom)) : 0;
      const desiredComposerGap = Math.max(2, Math.round(margin * 0.35));
      const panelViewportLimit = Math.max(220, Math.round(Math.min(viewportHeight - (margin * 2), panelBottom - margin)));
      const baseHeight = Math.round(Math.min(560, panelViewportLimit, Math.max(360, viewportHeight * 0.55)));
      const desiredHeight = Math.min(panelViewportLimit, Math.max(baseHeight, originalComposerGap + desiredComposerGap));
      const lift = Math.max(0, Math.round(desiredHeight - originalComposerGap + desiredComposerGap));

      const boundsCandidates = [
        referenceRect,
        document.getElementById("chat-input-container")?.getBoundingClientRect?.(),
        document.getElementById("input-section")?.getBoundingClientRect?.(),
        this.outputHost(host)?.getBoundingClientRect?.(),
        hostRect,
      ].filter((rect) => rect && rect.width > 0);
      const contentRect = boundsCandidates.find((rect) => rect.width >= 260) || hostRect;
      const viewportWidth = window.innerWidth || document.documentElement.clientWidth || hostRect.width || 1024;
      const viewportLeft = margin;
      const viewportRight = viewportWidth - margin;
      const panelLeft = Math.max(viewportLeft, Math.round(contentRect.left));
      const panelRight = Math.min(viewportRight, Math.round(contentRect.right));
      const panelWidth = Math.max(240, panelRight - panelLeft);
      const offsetLeft = Math.round((anchorRect.left || buttonRect.left) - panelLeft);
      const tabLeft = Math.max(0, Math.min(panelWidth - buttonRect.width, Math.round(buttonRect.left - panelLeft)));

      anchor.style.setProperty("--a0-hindsight-panel-width", `${Math.round(panelWidth)}px`);
      anchor.style.setProperty("--a0-hindsight-panel-height", `${desiredHeight}px`);
      anchor.style.setProperty("--a0-hindsight-panel-max-height", `${desiredHeight}px`);
      anchor.style.setProperty("--a0-hindsight-tab-offset-left", `${offsetLeft}px`);
      anchor.style.setProperty("--a0-hindsight-tab-width", `${Math.ceil(buttonRect.width)}px`);
      anchor.style.setProperty("--a0-hindsight-tab-left", `${tabLeft}px`);

      host.classList.add("a0-hindsight-host-lifted");
      host.style.setProperty("--a0-hindsight-panel-lift", `${lift}px`);
      this.liftComposerElements(host, lift);
      this.liftOutputHost(host, lift);
    } catch (_e) {}
  },

  schedulePlacementSync() {
    if (this.resizeRaf) window.cancelAnimationFrame(this.resizeRaf);
    this.resizeRaf = window.requestAnimationFrame(() => {
      this.resizeRaf = 0;
      if (this.visible) this.syncPanelPlacement();
    });
  },

  cleanupPanelLayout() {
    if (this.resizeRaf) window.cancelAnimationFrame(this.resizeRaf);
    this.resizeRaf = 0;
    this.clearComposerLift();
    this.clearOutputLift();
    const anchor = this.anchor();
    if (this.hostEl) {
      this.hostEl.classList.remove("a0-hindsight-host-lifted");
      this.hostEl.style.removeProperty("--a0-hindsight-panel-lift");
      this.hostEl = null;
    }
    if (anchor) {
      anchor.style.removeProperty("--a0-hindsight-panel-width");
      anchor.style.removeProperty("--a0-hindsight-panel-height");
      anchor.style.removeProperty("--a0-hindsight-panel-max-height");
      anchor.style.removeProperty("--a0-hindsight-tab-offset-left");
      anchor.style.removeProperty("--a0-hindsight-tab-width");
      anchor.style.removeProperty("--a0-hindsight-tab-left");
    }
    if (this.resizeListener) {
      window.removeEventListener("resize", this.resizeListener);
      window.removeEventListener("scroll", this.resizeListener, true);
      this.resizeListener = null;
    }
  },

  toggle() { this.visible ? this.close() : this.open(); },

  async open() {
    this.visible = true;
    if (!this.ctxid) this.ctxid = globalThis.Alpine?.store?.("chats")?.selected || "";
    await this.refresh({ force: true });
    this.resizeListener = () => this.schedulePlacementSync();
    window.addEventListener("resize", this.resizeListener);
    window.addEventListener("scroll", this.resizeListener, true);
    this.schedulePlacementSync();
  },

  close() {
    this.visible = false;
    this.cleanupPanelLayout();
  },

  async refresh({ force = false } = {}) {
    if (!this.ctxid) return;
    this.loading = true;
    try {
      const result = await callJsonApi("plugins/a0_hindsight/hindsight_agent_config_get", { ctxid: this.ctxid });
      if (!result?.ok) throw new Error(result?.error || "Failed to load Hindsight settings");
      this.projectName = result.project_name || "";
      this.agentProfile = result.agent_profile || "agent0";
      this.projectBankId = result.project_bank_id || "";
      this.agentBankId = result.agent_bank_id || "";
      this.retainBankIds = result.retain_bank_ids || [];
      this.recallBankIds = result.recall_bank_ids || [];
      this.settings = cloneSettings(result.settings || {});
      this.draft = cloneSettings(result.settings || {});
      this.schedulePlacementSync();
    } catch (e) {
      toastFrontendError(e.message || String(e), "Hindsight");
    } finally {
      this.loading = false;
    }
  },

  async save() {
    if (!this.ctxid) return;
    this.saving = true;
    try {
      const result = await callJsonApi("plugins/a0_hindsight/hindsight_agent_config_set", {
        ctxid: this.ctxid,
        settings: cloneSettings(this.draft),
      });
      if (!result?.ok) throw new Error(result?.error || "Failed to save Hindsight settings");
      this.settings = cloneSettings(this.draft);
      this.agentBankId = result.agent_bank_id || this.previewAgentBank();
      this.retainBankIds = result.retain_bank_ids || this.previewRetainBanks();
      this.recallBankIds = result.recall_bank_ids || this.previewRecallBanks();
      toastFrontendSuccess("Hindsight agent settings saved", "Hindsight");
      this.schedulePlacementSync();
    } catch (e) {
      toastFrontendError(e.message || String(e), "Hindsight");
    } finally {
      this.saving = false;
    }
  },

  hasUnsavedChanges() {
    return JSON.stringify(cloneSettings(this.draft)) !== JSON.stringify(cloneSettings(this.settings));
  },

  scopeLabel() {
    return `${this.agentProfile || "agent0"} · ${this.projectName || "default project"}`;
  },

  sanitizeBankPart(value, fallback = "agent0") {
    const text = String(value || fallback).trim().replace(/\s+/g, "-").replace(/[^A-Za-z0-9_.:-]+/g, "-").replace(/^[-._:]+|[-._:]+$/g, "");
    return text || fallback;
  },

  previewAgentBank() {
    return (this.draft.hindsight_agent_bank_id || "").trim() || this.sanitizeBankPart(this.agentProfile || "agent0");
  },

  previewRetainBanks() {
    if (!this.draft.hindsight_agent_memory_enabled) return [this.projectBankId].filter(Boolean);
    const banks = [this.previewAgentBank()];
    if (this.draft.hindsight_agent_retain_to_project && this.projectBankId && this.projectBankId !== banks[0]) banks.push(this.projectBankId);
    return banks.filter(Boolean);
  },

  previewRecallBanks() {
    if (!this.draft.hindsight_agent_memory_enabled) return [this.projectBankId].filter(Boolean);
    const banks = [this.previewAgentBank()];
    if (this.projectBankId && this.projectBankId !== banks[0]) banks.push(this.projectBankId);
    return banks.filter(Boolean);
  },
});
