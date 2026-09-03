import { useState, useEffect } from "react";
import type { ChangeEvent } from "react";

type UploadStatus = "idle" | "uploading" | "success" | "error"

const FileUpload = () => {
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<UploadStatus>("idle")

  useEffect(() => {
    if (status !== "success" && status !== "error") return;

    const timeoutId = setTimeout(() => setStatus("idle"), 3000);
    return () => clearTimeout(timeoutId);
  }, [status]);

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const selected = e.target.files?.[0] ?? null;
    setFile(selected);
  }

  async function handleFileUpload(){
    if (!file){
        return;
    }

    else{
        setStatus("uploading")
        const formData = new FormData();
        formData.append('file', file)

        try {
            const response = await fetch("http://127.0.0.1:8000/upload",
                {
                method: 'POST',
                body: formData
            });

            if (!response.ok) throw new Error("Upload failed")
            setStatus('success')
        }

        catch{
            setStatus('error')
        }
    }

  }

  return (
    <div className="file-upload">
      <input type="file" id="file-input" onChange={handleFileChange} />
      <p className="file-status">
        {file
          ? `Selected: ${file.name.length > 12 ? `${file.name.slice(0, 12)}…` : file.name}`
          : "No file selected"}
      </p>
      {file && status !== "uploading" && (
        <button type="button" className="upload-button" onClick={handleFileUpload}>
          Upload
        </button>
      )}
      {status === "success" && <p>File uploaded successfully</p>}

      {status === "error" && <p>Error uploading file, try again</p>}
    </div>
  );
};

export default FileUpload;
