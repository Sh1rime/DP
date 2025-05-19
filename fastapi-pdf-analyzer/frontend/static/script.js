// frontend/static/script.js

const form = document.getElementById('upload-form');
const statusDiv = document.getElementById('status');
const downloadBtn = document.getElementById('download-btn');
let currentTaskId = null;

form.addEventListener('submit', function(event) {
  event.preventDefault();  // отменяем стандартную отправку формы
  const fileInput = document.getElementById('pdf-file');
  if (!fileInput.files.length) {
    statusDiv.innerText = "Пожалуйста, выберите PDF-файл.";
    return;
  }
  const pdfFile = fileInput.files[0];
  const formData = new FormData();
  formData.append('file', pdfFile);

  // Отправляем файл на сервер
  statusDiv.innerText = "Отправка файла...";
  fetch('/api/v1/pdf', {
    method: 'POST',
    body: formData
  })
  .then(response => {
    if (!response.ok) {
      throw new Error(`Ошибка загрузки: ${response.statusText}`);
    }
    return response.json();
  })
  .then(data => {
    if (data.task_id) {
      currentTaskId = data.task_id;
      statusDiv.innerText = `Задача отправлена. ID: ${currentTaskId}. Ждите...`;
      pollStatus();  // запускаем опрос статуса
    } else {
      throw new Error("Не получен ID задачи");
    }
  })
  .catch(error => {
    console.error("Upload error:", error);
    statusDiv.innerText = "Ошибка при отправке файла: " + error.message;
  });
});

function pollStatus() {
  if (!currentTaskId) return;
  fetch(`/api/v1/status/${currentTaskId}`)
    .then(response => {
      if (!response.ok) {
        throw new Error("Failed to get status");
      }
      return response.json();
    })
    .then(data => {
      if (data.status) {
        statusDiv.innerText = "Статус задачи: " + data.status;
        if (data.status === "SUCCESS") {
          // Задача завершена успешно
          statusDiv.innerText = "Статус задачи: SUCCESS (завершена)";
          downloadBtn.style.display = "inline-block";
          downloadBtn.onclick = () => {
            // При клике перенаправляем на результат для скачивания
            window.location.href = `/api/v1/result/${currentTaskId}`;
          };
        } else if (data.status === "FAILURE") {
          statusDiv.innerText = "Статус задачи: FAILURE (произошла ошибка при анализе)";
        } else {
          // Если не завершена, повторно опрашиваем через 1 секунду
          setTimeout(pollStatus, 1000);
        }
      } else {
        throw new Error("Invalid status response");
      }
    })
    .catch(err => {
      console.error("Status poll error:", err);
      statusDiv.innerText = "Ошибка при получении статуса.";
    });
}
