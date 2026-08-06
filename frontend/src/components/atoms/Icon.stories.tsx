import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { Bell, MapPin, Trash2 } from "lucide-react";
import { Icon } from "./Icon";

const meta = {
  title: "Atoms/Icon",
  component: Icon,
  tags: ["autodocs"],
  args: { icon: MapPin },
} satisfies Meta<typeof Icon>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
export const Small: Story = { args: { size: "sm" } };
export const Large: Story = { args: { size: "lg" } };

export const Sizes: Story = {
  render: () => (
    <div className="flex items-end gap-4 text-fg-secondary">
      <Icon icon={Bell} size="sm" />
      <Icon icon={Bell} size="md" />
      <Icon icon={Bell} size="lg" />
    </div>
  ),
};

export const AccessibleLabel: Story = {
  args: { icon: Trash2, "aria-label": "삭제" },
};
