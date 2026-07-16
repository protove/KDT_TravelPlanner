import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { Input } from "./Input";

const meta = {
  title: "Atoms/Input",
  component: Input,
  tags: ["autodocs"],
} satisfies Meta<typeof Input>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = { args: { placeholder: "일정 검색" } };
export const WithValue: Story = { args: { defaultValue: "도쿄 벚꽃 여행" } };
export const Disabled: Story = { args: { placeholder: "입력 불가", disabled: true } };
