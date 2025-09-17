let canvas = document.getElementById('canvas');
let ctx = canvas.getContext('2d');
let img = new Image();
let startX, startY, isDrawing = false;
let currentSensor = null;

fetch('/sensors').then(r => r.json()).then(data => {
    let sel = document.getElementById('sensor');
    data.forEach(s => {
        let opt = document.createElement('option');
        opt.value = s.id;
        opt.innerText = s.id;
        sel.appendChild(opt);
    });
});

function loadImage() {
    currentSensor = document.getElementById('sensor').value;
    img.onload = function () {
        canvas.width = img.width; canvas.height = img.height;
        ctx.drawImage(img, 0, 0);
    };
    img.src = '/snapshot/' + currentSensor + '?t=' + Date.now();
}

canvas.onmousedown = e => {
    startX = e.offsetX; startY = e.offsetY; isDrawing = true;
};
canvas.onmouseup = e => {
    if (!isDrawing) return;
    isDrawing = false;
    let w = e.offsetX - startX;
    let h = e.offsetY - startY;
    ctx.strokeStyle = 'red'; ctx.lineWidth = 2;
    ctx.strokeRect(startX, startY, w, h);
    canvas.dataset.roi = [startX, startY, w, h];
};

function saveROI() {
    let roi = canvas.dataset.roi.split(',').map(x => parseInt(x));
    let roiType = document.getElementById('roiType').value;
    fetch('/save_roi', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sensor_id: currentSensor, roi_type: roiType, roi: roi })
    }).then(r => r.json()).then(j => {
        alert("Saved: " + JSON.stringify(roi));
    });
}
