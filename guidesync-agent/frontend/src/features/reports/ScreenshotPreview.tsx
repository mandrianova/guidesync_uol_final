import { Modal } from "@mantine/core";
import { IconExternalLink, IconMaximize, IconZoomIn } from "@tabler/icons-react";
import { useState } from "react";

import "./ScreenshotPreview.css";

interface ScreenshotPreviewProps {
  alt: string;
  height?: number | null;
  loading: "eager" | "lazy";
  onError: () => void;
  src: string;
  width?: number | null;
}

export function ScreenshotPreview({
  alt,
  height,
  loading,
  onError,
  src,
  width
}: ScreenshotPreviewProps) {
  const [opened, setOpened] = useState(false);
  const [fitToWindow, setFitToWindow] = useState(true);

  const close = () => {
    setOpened(false);
    setFitToWindow(true);
  };

  return (
    <>
      <button
        aria-label={`Open full-size preview: ${alt}`}
        className="public-change-evidence-trigger"
        onClick={() => setOpened(true)}
        type="button"
      >
        <img
          alt={alt}
          height={height || undefined}
          loading={loading}
          onError={onError}
          src={src}
          width={width || undefined}
        />
        <span className="public-change-evidence-zoom">
          <IconZoomIn aria-hidden size={17} />
          Open preview
        </span>
      </button>

      <Modal
        centered
        classNames={{
          body: "screenshot-preview-body",
          content: "screenshot-preview-content",
          header: "screenshot-preview-header",
          title: "screenshot-preview-title"
        }}
        closeButtonProps={{ "aria-label": "Close screenshot preview" }}
        fullScreen
        onClose={close}
        opened={opened}
        title={alt}
      >
        <div className="screenshot-preview-toolbar">
          <button
            aria-pressed={!fitToWindow}
            className="screenshot-preview-action"
            onClick={() => setFitToWindow((current) => !current)}
            type="button"
          >
            <IconMaximize aria-hidden size={17} />
            {fitToWindow ? "View actual size" : "Fit to window"}
          </button>
          <a
            className="screenshot-preview-action"
            href={src}
            rel="noreferrer"
            target="_blank"
          >
            <IconExternalLink aria-hidden size={17} />
            Open original
          </a>
        </div>
        <div
          className={
            fitToWindow
              ? "screenshot-preview-canvas screenshot-preview-canvas-fit"
              : "screenshot-preview-canvas screenshot-preview-canvas-actual"
          }
        >
          <img
            alt={alt}
            className="screenshot-preview-image"
            height={height || undefined}
            src={src}
            width={width || undefined}
          />
        </div>
      </Modal>
    </>
  );
}
