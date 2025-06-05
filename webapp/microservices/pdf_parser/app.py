import os,tempfile
from fastapi import FastAPI,UploadFile,File,HTTPException
from fastapi.responses import JSONResponse
from parser import parse_pdf

app=FastAPI(title="PDFParser Service")

@app.post("/parse")
async def parse_endpoint(file:UploadFile=File(...)):
    if file.content_type!="application/pdf": raise HTTPException(400,"Нужен PDF")
    data=await file.read()
    with tempfile.NamedTemporaryFile(delete=False,suffix=".pdf") as tmp:
        tmp.write(data); path=tmp.name
    try:
        res=parse_pdf(path)
    finally:
        os.remove(path)
    return JSONResponse(content=res)

if __name__=="__main__":
    import uvicorn; uvicorn.run(app,host="0.0.0.0",port=8001,reload=True)