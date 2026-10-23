<script lang="ts">
  import { metricMotion } from '../lib/motion';
  let { value, active = true }: { value: string; active?: boolean } = $props();
</script>

<!-- Paint the complete real value so units, selection and assistive reading stay intact. -->
<span class="animated-metric" use:metricMotion={active ? value : ''}>{value}</span>
