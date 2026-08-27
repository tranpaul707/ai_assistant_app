import { useState } from "react";
import type { ChangeEvent } from "react";

const FileUpload = () => {
  const [file, setFile] = useState<File | null>(null);

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const selected = e.target.files?.[0] ?? null;
    setFile(selected);
  }

  return (
    <div className="file-upload">
      <input type="file" id="file-input" onChange={handleFileChange} />
      <p className="file-status">
        {file
          ? `Selected: ${file.name.length > 12 ? `${file.name.slice(0, 12)}…` : file.name}`
          : "No file selected"}
      </p>
    </div>
  );
};

export default FileUpload;
