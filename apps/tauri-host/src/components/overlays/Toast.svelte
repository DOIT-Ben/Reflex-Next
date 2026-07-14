<script lang="ts">
  import CircleAlert from "@lucide/svelte/icons/circle-alert";
  import CircleCheck from "@lucide/svelte/icons/circle-check";

  interface Props {
    visible: boolean;
    message: string;
    tone?: "success" | "error";
  }

  let { visible, message, tone = "success" }: Props = $props();
</script>

{#if visible}
  <div
    class="toast"
    class:error={tone === "error"}
    role={tone === "error" ? "alert" : "status"}
    aria-live={tone === "error" ? "assertive" : "polite"}
  >
    {#if tone === "error"}<CircleAlert size={17} strokeWidth={2} />{:else}<CircleCheck size={17} strokeWidth={2} />{/if}
    <span>{message}</span>
  </div>
{/if}
