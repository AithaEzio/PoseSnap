<div class="creator-logo"><img src="/aitha-logo.png" alt="Aitha" width="72" height="72"/></div>

<style>
  .creator-logo{
    --logo-paper:color-mix(in srgb,var(--accent) 10%,#f4f6fc);
    position:relative;isolation:isolate;display:grid;place-items:center;flex-shrink:0;
    width:84px;height:84px;padding:5px;border-radius:14px;
    border:1px solid color-mix(in srgb,var(--accent) 42%,#d8dfef);
    background:
      radial-gradient(circle at 12% 0%,color-mix(in srgb,var(--accent) 28%,transparent),transparent 62%),
      radial-gradient(circle at 100% 100%,color-mix(in srgb,var(--glow) 14%,transparent),transparent 58%),
      linear-gradient(145deg,#fafbff,var(--logo-paper));
    box-shadow:0 3px 12px #0002,0 0 16px color-mix(in srgb,var(--accent) 9%,transparent),inset 0 1px 0 #fffe;
  }
  .creator-logo::before{content:'';position:absolute;inset:4px;border:1px solid #fff8;border-radius:10px;pointer-events:none}
  img{position:relative;width:72px;height:72px;object-fit:contain}
</style>
