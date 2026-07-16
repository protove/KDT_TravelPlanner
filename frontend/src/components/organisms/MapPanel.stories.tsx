import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { MapPanel } from "./MapPanel";

const meta = {
  title: "Organisms/MapPanel",
  component: MapPanel,
  tags: ["autodocs"],
} satisfies Meta<typeof MapPanel>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Empty: Story = {};

export const WithMarkers: Story = {
  args: {
    markers: [
      { id: "1", name: "나리타 국제공항", x: 20, y: 30 },
      { id: "2", name: "신주쿠 숙소", x: 55, y: 45 },
      { id: "3", name: "메이지 신궁", x: 40, y: 65 },
    ],
  },
};
