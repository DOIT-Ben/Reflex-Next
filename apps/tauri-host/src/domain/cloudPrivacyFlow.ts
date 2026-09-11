import { get, writable, type Writable } from "svelte/store";
import type {
  CloudConsent,
  CloudQualityRelease,
  CloudQuota,
  FeedbackBridge
} from "./feedbackBridge";
import type { ProviderAvailability } from "./providerCatalog";

export type CloudPrivacyFlowDeps = {
  feedbackBridge: () => FeedbackBridge | null;
  showToast: (message: string, tone?: "success" | "error") => void;
};

export type CloudPrivacyFlow = {
  consent: Writable<CloudConsent>;
  usageMetricsDraft: Writable<boolean>;
  improvementDraft: Writable<boolean>;
  qualityRelease: Writable<CloudQualityRelease | null>;
  quota: Writable<CloudQuota | null>;
  busy: Writable<boolean>;
  notice: Writable<string | null>;
  feedbackAvailable: Writable<boolean>;
  availability: Writable<ProviderAvailability>;
  hydrate: () => Promise<void>;
  saveDraft: () => Promise<boolean>;
  deleteAllData: () => Promise<void>;
};

const DEFAULT_CONSENT: CloudConsent = {
  usage_metrics: false,
  improvement_data: false,
  feedback_attachments: false,
  policy_version: "2026-07-14",
  updated_at: null
};

export function createCloudPrivacyFlow(deps: CloudPrivacyFlowDeps): CloudPrivacyFlow {
  const consent = writable<CloudConsent>(DEFAULT_CONSENT);
  const usageMetricsDraft = writable(false);
  const improvementDraft = writable(false);
  const qualityRelease = writable<CloudQualityRelease | null>(null);
  const quota = writable<CloudQuota | null>(null);
  const busy = writable(false);
  const notice = writable<string | null>(null);
  const feedbackAvailable = writable(false);
  const availability = writable<ProviderAvailability>("checking");

  async function hydrate() {
    const bridge = deps.feedbackBridge();
    if (!bridge || get(busy)) return;
    busy.set(true);
    availability.set("checking");
    notice.set(null);
    try {
      const [latestConsent, latestQuota, latestQualityRelease] = await Promise.all([
        bridge.getConsent(),
        bridge.getQuota(),
        bridge.getQualityRelease().catch(() => null)
      ]);
      consent.set(latestConsent);
      usageMetricsDraft.set(latestConsent.usage_metrics);
      improvementDraft.set(latestConsent.improvement_data);
      qualityRelease.set(latestQualityRelease);
      quota.set(latestQuota);
      feedbackAvailable.set(true);
      availability.set("ready");
    } catch {
      feedbackAvailable.set(false);
      availability.set("unavailable");
      notice.set("云端隐私设置暂不可用。");
    } finally {
      busy.set(false);
    }
  }

  async function saveDraft(): Promise<boolean> {
    const current = get(consent);
    if (
      get(usageMetricsDraft) === current.usage_metrics &&
      get(improvementDraft) === current.improvement_data
    ) return true;
    const bridge = deps.feedbackBridge();
    if (!bridge) {
      notice.set("当前环境无法保存云端隐私设置。");
      return false;
    }
    busy.set(true);
    notice.set(null);
    try {
      const saved = await bridge.updateConsent({
        ...current,
        usage_metrics: get(usageMetricsDraft),
        improvement_data: get(improvementDraft),
        policy_version: current.policy_version
      });
      consent.set(saved);
      usageMetricsDraft.set(saved.usage_metrics);
      improvementDraft.set(saved.improvement_data);
      notice.set("云端隐私设置已更新。");
      return true;
    } catch {
      consent.update(() => current);
      notice.set("云端隐私设置保存失败，请重试。");
      return false;
    } finally {
      busy.set(false);
    }
  }

  async function deleteAllData() {
    const bridge = deps.feedbackBridge();
    if (!bridge || get(busy)) return;
    busy.set(true);
    notice.set(null);
    try {
      await bridge.deleteCloudData();
      consent.set(DEFAULT_CONSENT);
      usageMetricsDraft.set(false);
      improvementDraft.set(false);
      quota.set(null);
      notice.set("云端数据已删除。");
      deps.showToast("云端数据已删除。", "success");
    } catch {
      notice.set("云端数据删除失败，请重试。");
    } finally {
      busy.set(false);
    }
  }

  return {
    consent,
    usageMetricsDraft,
    improvementDraft,
    qualityRelease,
    quota,
    busy,
    notice,
    feedbackAvailable,
    availability,
    hydrate,
    saveDraft,
    deleteAllData
  };
}
