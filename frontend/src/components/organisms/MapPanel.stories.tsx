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
      { id: "1", name: "나리타 국제공항", lat: 35.772, lng: 140.3929 },
      { id: "2", name: "신주쿠 숙소", lat: 35.6938, lng: 139.7034 },
      { id: "3", name: "메이지 신궁", lat: 35.6764, lng: 139.6993 },
    ],
  },
};
