import os,tempfile
from fastapi import FastAPI,UploadFile,File,HTTPException
from fastapi.responses import JSONResponse
from analyzer import analyze_pdf
app=FastAPI(title="Layout Analyzer")
@app.post("/analyze")
async def analyze_endpoint(file:UploadFile=File(...)):
    if file.content_type!="application/pdf": raise HTTPException(400,"Нужен PDF")
    data=await file.read()
    with tempfile.NamedTemporaryFile(delete=False,suffix=".pdf") as tmp:
        tmp.write(data); path=tmp.name
    try: res=analyze_pdf(path)
    finally: os.remove(path)
    return JSONResponse(content=res)

if __name__=="__main__": import uvicorn; uvicorn.run(app,host="0.0.0.0",port=8010,reload=True)