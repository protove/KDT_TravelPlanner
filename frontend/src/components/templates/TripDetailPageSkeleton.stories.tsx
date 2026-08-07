import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { TripDetailPageSkeleton } from "./TripDetailPageSkeleton";

const meta = {
  title: "Templates/TripDetailPageSkeleton",
  component: TripDetailPageSkeleton,
  tags: ["autodocs"],
  parameters: {
    layout: "fullscreen",
  },
} satisfies Meta<typeof TripDetailPageSkeleton>;

export default meta;
type Story = StoryObj<typeof meta>;

export const FullPage: Story = {
  args: {
    itemCount: 3,
  },
};

export const FewItems: Story = {
  args: {
    itemCount: 1,
  },
};
