import * as React from "react";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { Button } from "@/components/atoms/Button";
import type { Permission } from "@/components/molecules/PermissionSelect";
import { InviteDialog } from "./InviteDialog";

const meta = {
  title: "Organisms/InviteDialog",
  component: InviteDialog,
  tags: ["autodocs"],
} satisfies Meta<typeof InviteDialog>;

export default meta;
type Story = StoryObj<typeof meta>;

function Demo() {
  const [open, setOpen] = React.useState(false);
  const [nickname, setNickname] = React.useState("");
  const [permission, setPermission] = React.useState<Permission>("read");

  return (
    <>
      <Button onClick={() => setOpen(true)}>참여자 초대</Button>
      <InviteDialog
        open={open}
        onOpenChange={setOpen}
        nickname={nickname}
        onNicknameChange={setNickname}
        permission={permission}
        onPermissionChange={setPermission}
        onInvite={() => setOpen(false)}
      />
    </>
  );
}

const noopArgs = {
  open: false,
  onOpenChange: () => {},
  nickname: "",
  onNicknameChange: () => {},
  permission: "read" as Permission,
  onPermissionChange: () => {},
  onInvite: () => {},
};

export const Default: Story = { args: noopArgs, render: () => <Demo /> };

export const NotFound: Story = {
  args: { ...noopArgs, nickname: "존재하지않는닉네임", error: "해당 닉네임의 사용자를 찾을 수 없어요." },
  render: (args) => <InviteDialog {...args} open onOpenChange={() => {}} />,
};
