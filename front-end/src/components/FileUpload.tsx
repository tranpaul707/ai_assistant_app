import { useRef } from "react";
import type { ChangeEvent } from "react";

type UploadStatus = "idle" | "uploading";

interface FileUploadProps {
  file: File | null;
  status: UploadStatus;
  onFileChange: (file: File | null) => void;
  onStatusChange: (status: UploadStatus) => void;
}

const FileUpload = ({
  file,
  status,
  onFileChange,
  onStatusChange,
}: FileUploadProps) => {
  const inputRef = useRef<HTMLInputElement>(null);

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    onFileChange(e.target.files?.[0] ?? null);
  }

  async function handleFileUpload() {
    if (!file) return;

    onStatusChange("uploading");
    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch("http://127.0.0.1:8000/upload", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) throw new Error("Upload failed");
      alert("File uploaded successfully");
      onFileChange(null);
      if (inputRef.current) inputRef.current.value = "";
    } catch {
      alert("Error uploading file, try again");
    } finally {
      onStatusChange("idle");
    }
  }

  return (
    <div className="file-upload">
      <input
        ref={inputRef}
        type="file"
        id="file-input"
        onChange={handleFileChange}
      />
      {file && status !== "uploading" && (
        <button type="button" className="upload-button" onClick={() => void handleFileUpload()}>
          Upload
        </button>
      )}
    </div>
  );
};

export type { UploadStatus };
export default FileUpload;
