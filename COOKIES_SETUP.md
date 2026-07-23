# Configuração de Cookies para YouTube Scraper

## Problema
O YouTube bloqueia requisições de servidores cloud (como Render) com erro "Sign in to confirm you're not a bot". Para contornar isso, é necessário fornecer cookies autenticados de uma conta do YouTube.

## Solução
Configure cookies autenticados via variável de ambiente no Render.

## Passo 1: Exportar Cookies do Navegador

### Opção A: Extensão "Get cookies.txt LOCALLY" (Recomendada)
1. Instale a extensão "Get cookies.txt LOCALLY" no seu navegador (Chrome/Firefox)
2. Faça login no YouTube com sua conta
3. Clique na extensão e clique em "Export"
4. Salve o arquivo como `cookies.txt`

### Opção B: Manualmente
1. Faça login no YouTube
2. Abra as DevTools (F12)
3. Vá para a aba Application > Cookies > https://www.youtube.com
4. Copie os cookies importantes (SAPISID, HSID, SSID, APISID, SID, __Secure-3PAPISID)
5. Formate como arquivo cookies.txt no formato Netscape

## Passo 2: Converter para Base64

### No Linux/Mac:
```bash
base64 -w 0 cookies.txt
```

### No Windows (PowerShell):
```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("cookies.txt"))
```

### Online:
Use sites como https://www.base64encode.org/ para converter o conteúdo do arquivo

## Passo 3: Configurar no Render

1. Acesse o painel do Render: https://dashboard.render.com/
2. Selecione seu serviço "suamusica-api"
3. Vá para "Environment" 
4. Adicione nova variável de ambiente:
   - **Key**: `YOUTUBE_COOKIES_BASE64`
   - **Value**: Cole o valor base64 gerado no passo 2
5. Clique em "Save Changes"
6. O serviço reiniciará automaticamente

## Passo 4: Verificar

Após o reinício, verifique os logs do Render. Você deve ver:
```
INFO: Usando cookies base64 da variável de ambiente
```

## Alternativas

### Variável YOUTUBE_COOKIES_FROM_BROWSER
Se você tiver acesso ao sistema de arquivos do Render, pode usar:
- **Key**: `YOUTUBE_COOKIES_FROM_BROWSER`
- **Value**: `chrome`, `firefox`, `edge`, etc.

### Variável YOUTUBE_COOKIES_FILE
Se você puder fazer upload de arquivo:
- **Key**: `YOUTUBE_COOKIES_FILE`
- **Value**: Caminho completo para o arquivo cookies.txt

## Renovação de Cookies
Cookies do YouTube expiram periodicamente. Se o scraper começar a falhar novamente:
1. Repita o processo de exportação
2. Atualize a variável `YOUTUBE_COOKIES_BASE64` no Render
3. O serviço reiniciará automaticamente

## Notas de Segurança
- Nunca compartilhe seus cookies públicos
- Cookies dão acesso à sua conta do YouTube
- Use uma conta separada para automação se possível
- Renove cookies regularmente
