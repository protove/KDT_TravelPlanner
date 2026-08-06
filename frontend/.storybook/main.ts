import type { StorybookConfig } from "@storybook/nextjs-vite";

const config: StorybookConfig = {
  stories: ["../src/**/*.mdx", "../src/**/*.stories.@(js|jsx|mjs|ts|tsx)"],
  addons: ["@storybook/addon-a11y", "@storybook/addon-docs"],
  framework: "@storybook/nextjs-vite",
  staticDirs: ["../public"],
  // Docker Desktop(WSL2)의 /mnt/c NTFS bind mount에서는 Vite의 기본 native fs
  // watcher가 가짜 change 이벤트를 계속 만들어 HMR이 무한 반복되고, 그게 Docs 탭
  // 렌더링과 겹치면 빈 화면이 뜬다. WATCHPACK_POLLING은 webpack 전용이라 Vite엔
  // 적용되지 않으므로 여기서 직접 polling을 켠다.
  async viteFinal(viteConfig) {
    viteConfig.server = {
      ...viteConfig.server,
      watch: {
        ...viteConfig.server?.watch,
        usePolling: true,
        interval: 300,
      },
    };
    return viteConfig;
  },
};
export default config;
