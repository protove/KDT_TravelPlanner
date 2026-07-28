import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { TripsPageSkeleton } from "./TripsPageSkeleton";

const meta = {
  title: "Templates/TripsPageSkeleton",
  component: TripsPageSkeleton,
  tags: ["autodocs"],
  parameters: {
    layout: "fullscreen",
  },
} satisfies Meta<typeof TripsPageSkeleton>;

export default meta;
type Story = StoryObj<typeof meta>;

export const FullPage: Story = {
  args: {
    cardCount: 3,
  },
};

export const SmallScreenContent: Story = {
  args: {
    cardCount: 2,
  },
};
