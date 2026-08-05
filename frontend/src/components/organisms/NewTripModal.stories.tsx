import * as React from "react";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { Button } from "@/components/atoms/Button";
import { NewTripModal } from "./NewTripModal";

const meta = {
  title: "Organisms/NewTripModal",
  component: NewTripModal,
  tags: ["autodocs"],
} satisfies Meta<typeof NewTripModal>;

export default meta;
type Story = StoryObj<typeof meta>;

function Demo() {
  const [open, setOpen] = React.useState(false);

  return (
    <>
      <Button onClick={() => setOpen(true)}>+ 새 여행 만들기</Button>
      <NewTripModal open={open} onOpenChange={setOpen} accessToken={null} onCreated={() => {}} />
    </>
  );
}

export const Default: Story = {
  args: { open: false, onOpenChange: () => {}, accessToken: null, onCreated: () => {} },
  render: () => <Demo />,
};
