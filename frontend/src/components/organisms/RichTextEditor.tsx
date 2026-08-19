"use client";

import * as React from "react";
import { EditorContent, useEditor, useEditorState, type JSONContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Underline from "@tiptap/extension-underline";
import TextAlign from "@tiptap/extension-text-align";
import Image from "@tiptap/extension-image";
import {
  Bold,
  Italic,
  Underline as UnderlineIcon,
  Heading1,
  Heading2,
  Heading3,
  List,
  AlignLeft,
  AlignCenter,
  AlignRight,
  ImagePlus,
} from "lucide-react";
import { Button } from "@/components/atoms/Button";
import { Icon } from "@/components/atoms/Icon";
import { cn } from "@/lib/utils";
import type { TiptapDocument } from "@/lib/types/community";

export interface RichTextEditorProps {
  value: TiptapDocument;
  onChange: (doc: TiptapDocument) => void;
  readOnly?: boolean;
  placeholder?: string;
}

const EDITOR_CONTENT_CLASS = cn(
  "min-h-40 w-full text-sm leading-relaxed text-foreground focus-visible:outline-none",
  "[&_.ProseMirror]:min-h-40 [&_.ProseMirror]:focus-visible:outline-none",
  "[&_h1]:mt-4 [&_h1]:text-2xl [&_h1]:font-bold [&_h1]:first:mt-0",
  "[&_h2]:mt-4 [&_h2]:text-xl [&_h2]:font-bold [&_h2]:first:mt-0",
  "[&_h3]:mt-3 [&_h3]:text-lg [&_h3]:font-bold [&_h3]:first:mt-0",
  "[&_p]:mt-2 [&_p]:first:mt-0",
  "[&_ul]:mt-2 [&_ul]:list-disc [&_ul]:pl-5",
  "[&_li]:mt-1",
  "[&_img]:mt-2 [&_img]:max-w-full [&_img]:rounded-lg"
);

function RichTextEditor({ value, onChange, readOnly = false, placeholder }: RichTextEditorProps) {
  const editor = useEditor(
    {
      extensions: [
        StarterKit.configure({
          heading: { levels: [1, 2, 3] },
          underline: false,
          link: false,
          strike: false,
          code: false,
          codeBlock: false,
          blockquote: false,
          horizontalRule: false,
          orderedList: false,
        }),
        Underline,
        TextAlign.configure({
          types: ["paragraph", "heading"],
          alignments: ["left", "center", "right"],
        }),
        Image,
      ],
      content: value as JSONContent,
      editable: !readOnly,
      immediatelyRender: false,
      editorProps: {
        attributes: {
          class: EDITOR_CONTENT_CLASS,
          ...(placeholder ? { "data-placeholder": placeholder } : {}),
        },
      },
      onUpdate: ({ editor: updatedEditor }) => {
        onChange(updatedEditor.getJSON() as unknown as TiptapDocument);
      },
    },
    []
  );

  React.useEffect(() => {
    if (!editor || editor.isDestroyed) return;
    editor.setEditable(!readOnly);
  }, [editor, readOnly]);

  React.useEffect(() => {
    if (!editor || editor.isDestroyed) return;
    const isSameContent = JSON.stringify(editor.getJSON()) === JSON.stringify(value);
    if (isSameContent) return;
    editor.commands.setContent(value as JSONContent, { emitUpdate: false });
  }, [editor, value]);

  const editorState = useEditorState({
    editor,
    selector: ({ editor: currentEditor }) => {
      if (!currentEditor) return null;
      return {
        isBold: currentEditor.isActive("bold"),
        isItalic: currentEditor.isActive("italic"),
        isUnderline: currentEditor.isActive("underline"),
        isHeading1: currentEditor.isActive("heading", { level: 1 }),
        isHeading2: currentEditor.isActive("heading", { level: 2 }),
        isHeading3: currentEditor.isActive("heading", { level: 3 }),
        isBulletList: currentEditor.isActive("bulletList"),
        isAlignLeft: currentEditor.isActive({ textAlign: "left" }),
        isAlignCenter: currentEditor.isActive({ textAlign: "center" }),
        isAlignRight: currentEditor.isActive({ textAlign: "right" }),
      };
    },
  });

  const isEmpty = editor?.isEmpty ?? true;
  const showPlaceholder = Boolean(placeholder) && isEmpty && !readOnly;

  if (readOnly) {
    return (
      <div className="w-full">
        <EditorContent editor={editor} />
      </div>
    );
  }

  return (
    <div className="w-full rounded-lg border border-border bg-background">
      <div className="flex flex-wrap items-center gap-1 border-b border-border p-1.5">
        <ToolbarButton
          label="굵게"
          active={editorState?.isBold}
          onClick={() => editor?.chain().focus().toggleBold().run()}
        >
          <Icon icon={Bold} size="sm" />
        </ToolbarButton>
        <ToolbarButton
          label="기울임"
          active={editorState?.isItalic}
          onClick={() => editor?.chain().focus().toggleItalic().run()}
        >
          <Icon icon={Italic} size="sm" />
        </ToolbarButton>
        <ToolbarButton
          label="밑줄"
          active={editorState?.isUnderline}
          onClick={() => editor?.chain().focus().toggleUnderline().run()}
        >
          <Icon icon={UnderlineIcon} size="sm" />
        </ToolbarButton>
        <Divider />
        <ToolbarButton
          label="제목 1"
          active={editorState?.isHeading1}
          onClick={() => editor?.chain().focus().toggleHeading({ level: 1 }).run()}
        >
          <Icon icon={Heading1} size="sm" />
        </ToolbarButton>
        <ToolbarButton
          label="제목 2"
          active={editorState?.isHeading2}
          onClick={() => editor?.chain().focus().toggleHeading({ level: 2 }).run()}
        >
          <Icon icon={Heading2} size="sm" />
        </ToolbarButton>
        <ToolbarButton
          label="제목 3"
          active={editorState?.isHeading3}
          onClick={() => editor?.chain().focus().toggleHeading({ level: 3 }).run()}
        >
          <Icon icon={Heading3} size="sm" />
        </ToolbarButton>
        <Divider />
        <ToolbarButton
          label="목록"
          active={editorState?.isBulletList}
          onClick={() => editor?.chain().focus().toggleBulletList().run()}
        >
          <Icon icon={List} size="sm" />
        </ToolbarButton>
        <Divider />
        <ToolbarButton
          label="왼쪽 정렬"
          active={editorState?.isAlignLeft}
          onClick={() => editor?.chain().focus().setTextAlign("left").run()}
        >
          <Icon icon={AlignLeft} size="sm" />
        </ToolbarButton>
        <ToolbarButton
          label="가운데 정렬"
          active={editorState?.isAlignCenter}
          onClick={() => editor?.chain().focus().setTextAlign("center").run()}
        >
          <Icon icon={AlignCenter} size="sm" />
        </ToolbarButton>
        <ToolbarButton
          label="오른쪽 정렬"
          active={editorState?.isAlignRight}
          onClick={() => editor?.chain().focus().setTextAlign("right").run()}
        >
          <Icon icon={AlignRight} size="sm" />
        </ToolbarButton>
        <Divider />
        <ToolbarButton
          label="이미지 추가"
          onClick={() => {
            const src = window.prompt("이미지 URL을 입력하세요");
            if (!src) return;
            editor?.chain().focus().setImage({ src }).run();
          }}
        >
          <Icon icon={ImagePlus} size="sm" />
        </ToolbarButton>
      </div>
      <div className="relative px-3 py-2">
        {showPlaceholder && (
          <span className="pointer-events-none absolute left-3 top-2 text-sm text-fg-secondary">
            {placeholder}
          </span>
        )}
        <EditorContent editor={editor} />
      </div>
    </div>
  );
}

interface ToolbarButtonProps {
  label: string;
  active?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}

function ToolbarButton({ label, active, onClick, children }: ToolbarButtonProps) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      aria-label={label}
      aria-pressed={active}
      className={cn("h-8 w-8", active && "bg-muted")}
      onClick={onClick}
    >
      {children}
    </Button>
  );
}

function Divider() {
  return <div className="mx-0.5 h-5 w-px bg-border" />;
}

export { RichTextEditor };
