<script lang="ts">
  export let as: "section" | "article" | "aside" | "div" = "section";
  export let tone: "default" | "strong" | "quiet" = "default";
</script>

<svelte:element this={as} class={`ui-glass-panel ${tone}`}><slot /></svelte:element>
