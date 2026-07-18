import { toast } from "sonner";

export function comingInV1(featureName?: string): void {
  toast.info(featureName ? `${featureName} coming in v1` : "Coming in v1", {
    description: "v0 is read-only. Write actions land in v1.",
  });
}
