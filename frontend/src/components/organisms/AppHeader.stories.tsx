import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { AppHeader } from "./AppHeader";

const meta = {
  title: "Organisms/AppHeader",
  component: AppHeader,
  tags: ["autodocs"],
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof AppHeader>;

export default meta;
type Story = StoryObj<typeof meta>;

export const LoggedIn: Story = { args: { loggedIn: true, userInitial: "지" } };
export const LoggedOut: Story = { args: { loggedIn: false } };
