import * as React from "react";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { PermissionSelect, type Permission } from "./PermissionSelect";

const meta = {
  title: "Molecules/PermissionSelect",
  component: PermissionSelect,
  tags: ["autodocs"],
} satisfies Meta<typeof PermissionSelect>;

export default meta;
type Story = StoryObj<typeof meta>;

function ControlledPermissionSelect({ initial }: { initial: Permission }) {
  const [value, setValue] = React.useState<Permission>(initial);
  return <PermissionSelect value={value} onChange={setValue} />;
}

export const Read: Story = {
  args: { value: "read" },
  render: () => <ControlledPermissionSelect initial="read" />,
};

export const Write: Story = {
  args: { value: "write" },
  render: () => <ControlledPermissionSelect initial="write" />,
};

export const Disabled: Story = {
  args: { value: "read", disabled: true },
};
