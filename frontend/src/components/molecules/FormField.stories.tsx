import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { Input } from "@/components/atoms/Input";
import { Textarea } from "@/components/atoms/Textarea";
import { FormField } from "./FormField";

const meta = {
  title: "Molecules/FormField",
  component: FormField,
  tags: ["autodocs"],
} satisfies Meta<typeof FormField>;

export default meta;
type Story = StoryObj<typeof meta>;

const noopArgs = { label: "", children: null };

export const Default: Story = {
  args: noopArgs,
  render: () => (
    <FormField label="여행 제목" htmlFor="trip-title" required>
      <Input id="trip-title" placeholder="도쿄 벚꽃 여행" />
    </FormField>
  ),
};

export const WithDescription: Story = {
  args: noopArgs,
  render: () => (
    <FormField label="여행 설명" htmlFor="trip-desc" description="참여자 모두에게 보이는 소개글이에요.">
      <Textarea id="trip-desc" placeholder="여행 설명을 입력하세요" />
    </FormField>
  ),
};

export const WithError: Story = {
  args: noopArgs,
  render: () => (
    <FormField label="여행 제목" htmlFor="trip-title-error" error="제목을 입력해주세요.">
      <Input id="trip-title-error" />
    </FormField>
  ),
};
