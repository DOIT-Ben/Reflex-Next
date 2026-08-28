<script lang="ts">
  export let title: string;
  export let description = "";
</script>

<section class="ui-dialog-shell" aria-label={title}><header><div><h2>{title}</h2>{#if description}<p>{description}</p>{/if}</div><slot name="actions" /></header><div class="ui-dialog-content"><slot /></div><footer><slot name="footer" /></footer></section>
