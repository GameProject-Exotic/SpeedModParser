# How to use:

## 1. Copy this repo
## 2. Download [bspsrc jar file](https://github.com/ata4/bspsrc/releases/download/v1.4.8/bspsrc-jar-only.zip)
## 3. Copy jar file to repo directory or change BSPSRC_JAR file directory in main.py
## 4. Run via `python main.py [map name.bsp]`

# Примеры использования
## 1. Минимальный вывод (только имена, тип, центры брашей):
`python parser.py map.bsp`
### Вывод:
```
1. nojump [nojump]
512.00 256.00 128.00

2. noflash1 [noflash]
768.00 128.00 64.00
768.00 384.00 64.00
```
## 2. С outputs и origins:
`python parser.py map.bsp --outputs --origins`
## 3. Показать min/max вместо центров:
`python parser.py map.bsp --coords`
## 4. Всё подряд (verbose):
`python parser.py map.bsp --verbose`
## 5. Не показывать центры, только outputs и классификацию:
`python parser.py map.bsp --outputs --no-centers`
