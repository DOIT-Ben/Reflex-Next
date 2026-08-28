<script lang="ts">
  export let title: string;
  export let detail = "";
  export let tone: "default" | "error" = "default";
</script>

<div class={`ui-empty-state ${tone}`}><strong>{title}</strong>{#if detail}<span>{detail}</span>{/if}<slot /></div>
