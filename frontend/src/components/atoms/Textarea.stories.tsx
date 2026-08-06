import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { Textarea } from "./Textarea";

const meta = {
  title: "Atoms/Textarea",
  component: Textarea,
  tags: ["autodocs"],
} satisfies Meta<typeof Textarea>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = { args: { placeholder: "여행 설명을 입력하세요" } };
export const WithValue: Story = { args: { defaultValue: "벚꽃 시즌에 맞춰 도쿄 곳곳을 둘러보는 4박 5일 일정입니다." ,"aria-label": "여행 설명" ,} };
export const Disabled: Story = { args: { placeholder: "입력 불가", disabled: true } };
